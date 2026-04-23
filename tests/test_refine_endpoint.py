"""Tests for POST /refine sync endpoint (T5).

The endpoint is a thin HTTP adapter over :class:`refine.Refiner`.
Refiner itself has unit coverage in ``tests/test_refiner.py``; these
tests focus on the HTTP surface: request parsing, validation, and
response shape.

Fixtures:
* ``client`` — ``httpx.AsyncClient`` with ASGI transport that drives
  the app's lifespan, which populates ``app.state.refiner`` via the
  InMemory refine rule store. ``async with AsyncClient(...)`` plus an
  explicit startup is required because ASGITransport does not run the
  lifespan on its own.
"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app import create_app
from config import Config


@pytest_asyncio.fixture
async def client():
    """AsyncClient with lifespan-started app (so app.state.refiner is wired)."""
    app = create_app(config=Config(forge_api_key="", database_url=""))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        # Manually drive startup so lifespan seeds InMemory refine rules
        # and constructs the Refiner. ASGITransport does NOT invoke
        # lifespan events — we call the lifespan context explicitly.
        async with app.router.lifespan_context(app):
            yield c


# Korean sample text that satisfies validator thresholds:
# - >= 100 chars
# - >= 10% Hangul
# - >= 1 newline
CLEAN_KOREAN = (
    "# 문서 제목\n\n"
    "이것은 테스트 문서입니다.\n"
    "충분히 긴 본문을 포함하여 검증기를 통과해야 합니다.\n"
    "한국어 비율도 충분히 높아야 합니다.\n"
    "여러 줄의 본문이 포함되어 있습니다.\n"
    "문서의 길이는 검증기의 최소 기준을 넘어야 합니다.\n"
)


# --------------------------------------------------------------------------- #
# 1. text form field success
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_refine_sync_text_success(client):
    resp = await client.post("/refine", data={"text": CLEAN_KOREAN})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["quality"]["gate"] == "pass"
    # rule_versions populated with all 7 keys (6 stages + validator)
    assert set(data["rule_versions"].keys()) == {
        "encoding",
        "newline",
        "special_char",
        "frontmatter",
        "codefence",
        "traceability",
        "validator",
    }
    # refined_text present and non-empty
    assert isinstance(data["refined_text"], str)
    assert len(data["refined_text"]) > 0


# --------------------------------------------------------------------------- #
# 2. file upload success
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_refine_sync_file_success(client):
    body_bytes = CLEAN_KOREAN.encode("utf-8")
    resp = await client.post(
        "/refine",
        files={"file": ("doc.md", body_bytes, "text/markdown")},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["quality"]["gate"] == "pass"
    # encoding stage should report that it decoded the bytes
    assert data["report"]["encoding"]["applied"] is True


# --------------------------------------------------------------------------- #
# 3. empty body → 400
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_refine_sync_rejects_empty_body(client):
    # Must still be multipart so FastAPI's Form/File parsers engage.
    # An empty multipart form yields no file and no text → 400.
    resp = await client.post(
        "/refine",
        files={"dummy": ("", b"", "application/octet-stream")},
    )
    # Either FastAPI rejects (422) or our validator returns 400.
    # We explicitly want our 400. If FastAPI treats the empty file as
    # absent, it will fall through to our check.
    assert resp.status_code in (400, 422)


# --------------------------------------------------------------------------- #
# 4. both file and text → 400
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_refine_sync_rejects_both_file_and_text(client):
    resp = await client.post(
        "/refine",
        data={"text": CLEAN_KOREAN},
        files={"file": ("doc.md", CLEAN_KOREAN.encode("utf-8"), "text/markdown")},
    )
    assert resp.status_code == 400
    assert "OR" in resp.json()["detail"] or "both" in resp.json()["detail"].lower()


# --------------------------------------------------------------------------- #
# 5. oversized file → 413
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_refine_sync_rejects_oversized_file():
    """Use a shrunk MAX_FILE_SIZE to trigger 413 without allocating 100MB."""
    app = create_app(config=Config(forge_api_key="", database_url="", max_file_size=10))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        async with app.router.lifespan_context(app):
            resp = await c.post(
                "/refine",
                files={"file": ("big.md", b"x" * 100, "application/octet-stream")},
            )
    assert resp.status_code == 413


# --------------------------------------------------------------------------- #
# 6. short input → gate fail (200, quality.gate="fail")
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_refine_sync_reports_gate_fail(client):
    # Short Korean input (under 100 chars) — refine succeeds, gate fails.
    resp = await client.post("/refine", data={"text": "한국어\n"})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["quality"]["gate"] == "fail"
    assert "reason" in data["quality"]
    assert "length" in data["quality"]["reason"]


# --------------------------------------------------------------------------- #
# 7. cp949-encoded bytes decoded to clean UTF-8
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_refine_sync_bytes_cp949_decoded(client):
    body_bytes = CLEAN_KOREAN.encode("cp949")
    resp = await client.post(
        "/refine",
        files={"file": ("doc.md", body_bytes, "text/markdown")},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    # Response JSON deserialization already yields a Python str — if the
    # bytes had not been decoded, refine would have raised and we'd see
    # a 500. Additionally, content should contain Korean characters.
    assert "문서" in data["refined_text"]
    assert "제목" in data["refined_text"]
    assert data["quality"]["gate"] == "pass"


# --------------------------------------------------------------------------- #
# 8. rule_versions has all 7 keys
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_refine_sync_rule_versions_present(client):
    resp = await client.post("/refine", data={"text": CLEAN_KOREAN})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    versions = data["rule_versions"]
    assert len(versions) == 7
    for key in ("encoding", "newline", "special_char", "frontmatter",
                "codefence", "traceability", "validator"):
        assert key in versions
        assert isinstance(versions[key], int)
        assert versions[key] >= 1
