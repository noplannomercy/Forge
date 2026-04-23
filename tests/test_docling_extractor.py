"""Tests for extractors/docling_ex.py — Option B (HTTP) implementation.

All tests mock the HTTP layer (``httpx.AsyncClient.post``) — never hit the real
docling-serve. Uses ``Config(_env_file=None, ...)`` to isolate from the local
``.env`` file where needed.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

import extractors.docling_ex as docling_ex


FIXTURE_PDF = "tests/file/golf-rule-modifications-2026.pdf"


@pytest.fixture(autouse=True)
def _reset_semaphore():
    """Reset the module-level shared semaphore between tests to avoid
    size-mismatch when a previous test instantiated it with a different
    vlm_concurrency. Tests run in a fresh asyncio event loop per case,
    so the Semaphore would otherwise be bound to a dead loop."""
    docling_ex._DOCLING_SEMAPHORE = None
    yield
    docling_ex._DOCLING_SEMAPHORE = None


def _ok_response(md: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "document": {"md_content": md, "filename": "x.pdf"},
            "status": "success",
            "processing_time": 1.2,
        },
    )


def _isolated_config(**overrides):
    """Build a Config that ignores .env, so tests are hermetic."""
    from config import Config
    return Config(_env_file=None, **overrides)


@pytest.mark.asyncio
async def test_docling_ex_happy_path_http_200():
    """Mock docling-serve 200 → returns ConvertResult with md + method='docling'."""
    md = "## Title\n\nBody text here." * 200  # long enough to avoid fallback
    mock_response = _ok_response(md)

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
        cfg = _isolated_config(docling_serve_url="http://mock:5001", docling_api_key=None)
        result = await docling_ex.extract(b"%PDF-fake", "x.pdf", config=cfg)

    assert result.route == "docling"
    assert result.quality.method == "docling"
    assert "## Title" in result.text
    assert result.source_format == "pdf"
    assert result.pages >= 1


@pytest.mark.asyncio
async def test_docling_ex_fallback_when_url_not_configured():
    """No DOCLING_SERVE_URL → immediate fallback without any HTTP call."""
    cfg = _isolated_config(docling_serve_url=None)
    with open(FIXTURE_PDF, "rb") as f:
        pdf_bytes = f.read()

    # Also guard that no HTTP is made.
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        result = await docling_ex.extract(pdf_bytes, "x.pdf", config=cfg)
        mock_post.assert_not_called()

    assert result.quality.method == "pypdfium2_fallback"
    assert result.route == "docling"  # still reports as docling even on fallback


@pytest.mark.asyncio
async def test_docling_ex_fallback_on_http_500():
    """docling-serve returns 500 → fallback to pypdfium2."""
    mock_response = httpx.Response(500, text="internal error")
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
        cfg = _isolated_config(docling_serve_url="http://mock:5001")
        with open(FIXTURE_PDF, "rb") as f:
            pdf_bytes = f.read()
        result = await docling_ex.extract(pdf_bytes, "x.pdf", config=cfg)

    assert result.quality.method == "pypdfium2_fallback"
    assert result.route == "docling"


@pytest.mark.asyncio
async def test_docling_ex_fallback_on_network_error():
    """Network error (connection refused) → fallback."""
    with patch(
        "httpx.AsyncClient.post",
        new_callable=AsyncMock,
        side_effect=httpx.ConnectError("connection refused"),
    ):
        cfg = _isolated_config(docling_serve_url="http://mock:5001")
        with open(FIXTURE_PDF, "rb") as f:
            pdf_bytes = f.read()
        result = await docling_ex.extract(pdf_bytes, "x.pdf", config=cfg)

    assert result.quality.method == "pypdfium2_fallback"


@pytest.mark.asyncio
async def test_docling_ex_passes_api_key_header():
    """With DOCLING_API_KEY set, X-Api-Key header is added to the request."""
    mock_response = _ok_response("x" * 5000)
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response) as mock_post:
        cfg = _isolated_config(docling_serve_url="http://mock:5001", docling_api_key="secret-key")
        await docling_ex.extract(b"%PDF-fake", "x.pdf", config=cfg)

    # Inspect the kwargs used on the call.
    _, call_kwargs = mock_post.call_args
    assert call_kwargs["headers"]["X-Api-Key"] == "secret-key"


@pytest.mark.asyncio
async def test_docling_ex_logs_to_store_on_success():
    """DoclingLogStore (if provided) gets an entry on success with fallback=False."""
    mock_log_store = AsyncMock()
    mock_response = _ok_response("x" * 5000)
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
        cfg = _isolated_config(docling_serve_url="http://mock:5001")
        await docling_ex.extract(
            b"%PDF-fake", "x.pdf",
            config=cfg,
            docling_log_store=mock_log_store,
            job_id="test-job-id",
        )

    mock_log_store.insert.assert_called_once()
    _, call_kwargs = mock_log_store.insert.call_args
    assert call_kwargs["fallback"] is False
    assert call_kwargs["status_code"] == 200
    assert call_kwargs["job_id"] == "test-job-id"
    assert call_kwargs["reason"] is None


@pytest.mark.asyncio
async def test_docling_ex_empty_md_content_falls_back():
    """Empty md_content in a 200 response → treat as failure, fallback."""
    mock_response = httpx.Response(
        200,
        json={
            "document": {"md_content": "", "filename": "x.pdf"},
            "status": "success",
            "processing_time": 1.0,
        },
    )
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
        cfg = _isolated_config(docling_serve_url="http://mock:5001")
        with open(FIXTURE_PDF, "rb") as f:
            pdf_bytes = f.read()
        result = await docling_ex.extract(pdf_bytes, "x.pdf", config=cfg)

    assert result.quality.method == "pypdfium2_fallback"


@pytest.mark.asyncio
async def test_docling_ex_s4_signature_compliance():
    """Can be called with the S4 signature (bytes, name) without extra kwargs.

    We patch ``config.Config`` inside the lazy import so the no-config test
    is hermetic even when .env or os-env supplies DOCLING_SERVE_URL on the
    developer box.
    """
    cfg = _isolated_config(docling_serve_url=None)
    # Patch the Config class that docling_ex does a lazy `from config import Config`
    # on so the instance it creates has no DOCLING_SERVE_URL regardless of env.
    with patch("config.Config", return_value=cfg):
        with open(FIXTURE_PDF, "rb") as f:
            pdf_bytes = f.read()
        result = await docling_ex.extract(pdf_bytes, "x.pdf")

    assert result.quality.method == "pypdfium2_fallback"
    assert result.route == "docling"
