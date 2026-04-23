"""Tests for POST /reverse-doc async endpoint (T10).

The endpoint uploads source code, creates a Job with route=reverse_doc,
and dispatches a worker task that runs the ReverseDocGenerator.

Fixtures follow the pattern from test_refine_endpoint.py:
* lifespan OUTER / AsyncClient INNER — so app.state.revdoc_generator
  is wired before the client issues requests.
* VLM is mocked at the VLMClient.process_text level (the generator
  duck-types through vlm.process_text).

Job completion is polled via store.get(job_id) with asyncio.wait_for
to avoid racy sleeps.
"""

from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock, patch

from app import create_app
from config import Config
from models import JobStatus


# --------------------------------------------------------------------------- #
# Helpers — copied pattern from test_revdoc_generator.py to keep tests
# self-contained. Keep in sync if the gate schema changes.
# --------------------------------------------------------------------------- #


def _valid_md(pad_chars: int = 900) -> str:
    """Reverse-doc MD that passes every gate check."""
    head = (
        "## 업무목적\n본 코드는 고객 등급 산출 로직을 구현한다.\n\n"
        "## 처리흐름\n1. 입력 수신\n2. 규칙 평가\n3. 결과 반환\n\n"
        "## 입력/출력\n- 입력: customer_id (str)\n- 출력: tier (str)\n\n"
        "## 규칙/예외\n- total_amount > 1000 이면 GOLD\n- 예외 시 BRONZE\n\n"
        "## 근거\n사내 고객 정책 문서 R-001 근거로 작성.\n\n"
        "## 추적성\n"
        "- Rule: R-001 고객 등급 산출\n"
        "- Condition: total_amount > 1000 AND tier = 'GOLD'\n"
        "- Evidence: customer_tier.py:45\n\n"
        "## 관련업무\n- 선행: 주문 집계\n- 후행: 혜택 부여\n"
    )
    pad = ("한국어 본문 추가 설명입니다.\n" * 100)[:pad_chars]
    return head + pad


def _invalid_md() -> str:
    """MD missing ## 처리흐름 section — gate fails on sections check."""
    md = _valid_md(pad_chars=900)
    return md.replace(
        "## 처리흐름\n1. 입력 수신\n2. 규칙 평가\n3. 결과 반환\n\n", ""
    )


async def _wait_for_completion(store, job_id: str, timeout: float = 5.0):
    """Poll store until job.status is completed or failed."""
    async def _poll():
        while True:
            job = await store.get(job_id)
            if job and job.status in (JobStatus.COMPLETED, JobStatus.FAILED):
                return job
            await asyncio.sleep(0.05)

    return await asyncio.wait_for(_poll(), timeout=timeout)


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest_asyncio.fixture
async def app_and_client():
    """App + client with lifespan driven so state.revdoc_generator is wired."""
    app = create_app(config=Config(forge_api_key="", database_url=""))
    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield app, c


@pytest_asyncio.fixture
async def client_with_mock_vlm(app_and_client):
    """Patch process_text on the already-instantiated revdoc VLMClient.

    The generator holds a reference to app.state.revdoc_vlm, so patching
    the instance attribute intercepts all calls without rebuilding state.
    """
    app, c = app_and_client
    # Default: VLM returns valid MD → gate passes on first try.
    app.state.revdoc_vlm.process_text = AsyncMock(return_value=_valid_md())
    yield app, c


# --------------------------------------------------------------------------- #
# 1. Basic dispatch — returns job_id + queued
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_reverse_doc_creates_job(client_with_mock_vlm):
    app, c = client_with_mock_vlm
    resp = await c.post(
        "/reverse-doc",
        files={"file": ("sample.pkb", b"BEGIN NULL; END;", "application/octet-stream")},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "job_id" in data
    # Queued (or already running — both acceptable race outcomes).
    assert data["status"] in ("queued", "processing", "completed")


# --------------------------------------------------------------------------- #
# 2. Oversized file — 413
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_reverse_doc_rejects_oversized(client_with_mock_vlm):
    _, c = client_with_mock_vlm
    big = b"x" * (200 * 1024 + 1)
    resp = await c.post(
        "/reverse-doc",
        files={"file": ("big.pkb", big, "application/octet-stream")},
    )
    assert resp.status_code == 413
    assert "200KB" in resp.json()["detail"]


# --------------------------------------------------------------------------- #
# 3. Missing file — 422 (FastAPI auto-reject)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_reverse_doc_missing_file(client_with_mock_vlm):
    _, c = client_with_mock_vlm
    resp = await c.post("/reverse-doc", data={})
    assert resp.status_code == 422


# --------------------------------------------------------------------------- #
# 4. End-to-end pass — VLM returns valid MD, job completes.
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_reverse_doc_end_to_end_pass(client_with_mock_vlm):
    app, c = client_with_mock_vlm

    resp = await c.post(
        "/reverse-doc",
        files={"file": ("tier.pkb", b"BEGIN NULL; END;", "application/octet-stream")},
    )
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]

    job = await _wait_for_completion(app.state.store, job_id)

    assert job.status == JobStatus.COMPLETED
    assert job.result is not None
    assert job.result.route == "reverse_doc"
    assert job.result.quality.method == "reverse_doc"
    assert job.result.quality.confidence == "high"
    assert len(job.result.text) > 0
    # Meta carries revdoc bookkeeping.
    assert job.meta["revdoc_gate"]["passed"] is True
    assert job.meta["attempts"] == 1
    assert job.meta_prompt_version == "reverse_doc-v1"


# --------------------------------------------------------------------------- #
# 5. End-to-end gate fail — VLM always returns bad MD.
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_reverse_doc_end_to_end_gate_fail(app_and_client):
    app, c = app_and_client
    # Always return MD missing ## 처리흐름 → gate fails on every attempt.
    app.state.revdoc_vlm.process_text = AsyncMock(return_value=_invalid_md())

    resp = await c.post(
        "/reverse-doc",
        files={"file": ("bad.pkb", b"BEGIN NULL; END;", "application/octet-stream")},
    )
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]

    job = await _wait_for_completion(app.state.store, job_id)

    # Even on gate fail the job completes — the last attempt's MD is stored.
    assert job.status == JobStatus.COMPLETED
    assert job.result.quality.confidence == "low"
    assert job.meta["revdoc_gate"]["passed"] is False
    assert job.meta["attempts"] == 3  # default max_retries=2 → 3 total
    # VLM was invoked 3 times via the generator.
    assert app.state.revdoc_vlm.process_text.await_count == 3


# --------------------------------------------------------------------------- #
# 6. Callback uses CALLBACK_FIELD_MAP rename.
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_reverse_doc_callback_uses_field_rename():
    """Same field-rename path as /convert — reverse_doc must not bypass it."""
    app = create_app(config=Config(
        forge_api_key="",
        database_url="",
        callback_field_map='{"content":"text","file_name":"file_source"}',
        callback_keep_unmapped=True,
    ))
    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        app.state.revdoc_vlm.process_text = AsyncMock(return_value=_valid_md())
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            with patch("worker._send_callback", new_callable=AsyncMock) as mock_cb:
                resp = await c.post(
                    "/reverse-doc",
                    files={"file": ("x.pkb", b"BEGIN NULL; END;", "application/octet-stream")},
                    data={"callback_url": "http://consumer/ingest"},
                )
                assert resp.status_code == 200
                job_id = resp.json()["job_id"]
                await _wait_for_completion(app.state.store, job_id)

    mock_cb.assert_called_once()
    url_arg, payload_arg = mock_cb.call_args[0][0], mock_cb.call_args[0][1]
    assert url_arg == "http://consumer/ingest"
    # Keys renamed.
    assert "text" in payload_arg
    assert "file_source" in payload_arg
    assert "content" not in payload_arg
    assert "file_name" not in payload_arg


# --------------------------------------------------------------------------- #
# 7. requested_by is persisted on the Job.
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_reverse_doc_requested_by_persisted(client_with_mock_vlm):
    app, c = client_with_mock_vlm
    resp = await c.post(
        "/reverse-doc",
        files={"file": ("x.pkb", b"BEGIN NULL; END;", "application/octet-stream")},
        data={"requested_by": "devops-eng"},
    )
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]
    # Read immediately — requested_by is set at create() time before dispatch.
    job = await app.state.store.get(job_id)
    assert job.requested_by == "devops-eng"
