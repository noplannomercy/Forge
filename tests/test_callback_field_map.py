"""Tests for consumer-agnostic callback field rename (T0 of v3 LightRAG extension).

Validates worker.process_job applies `callback_field_map` JSON transform
to the outgoing callback payload, without any consumer-specific branching.
"""
import pytest
from unittest.mock import AsyncMock, patch

from config import Config
from models import ConvertResult, Quality
from worker import process_job


@pytest.fixture
def mock_result():
    return ConvertResult(
        text="# Hello", format="md", pages=1, file_name="test.docx",
        source_format="docx", route="extract",
        quality=Quality(
            total_chars=7, chars_per_page=7, total_pages=1,
            failed_pages=0, confidence="high", method="extract",
        ),
    )


@pytest.mark.asyncio
async def test_callback_renames_fields_with_map(store, mock_result):
    """With callback_field_map set and keep_unmapped=False, only mapped keys remain."""
    config = Config(
        callback_field_map='{"content":"text","file_name":"file_source"}',
        callback_keep_unmapped=False,
    )
    job = await store.create(
        "test.docx", "docx", "extract",
        callback_url="http://downstream/ingest",
    )
    with patch("worker.EXTRACTORS", {"docx": AsyncMock(return_value=mock_result)}):
        with patch("worker.MetaExtractor") as MockMeta:
            mock_meta = AsyncMock()
            mock_meta.extract = AsyncMock(return_value={})
            mock_meta.close = AsyncMock()
            MockMeta.return_value = mock_meta
            with patch("worker._send_callback", new_callable=AsyncMock) as mock_cb:
                await process_job(job, b"fake", "extract", store, config)

    mock_cb.assert_called_once()
    sent_payload = mock_cb.call_args[0][1]
    # After rename: content→text, file_name→file_source.
    assert "text" in sent_payload
    assert sent_payload["text"] == "# Hello"
    assert "file_source" in sent_payload
    assert sent_payload["file_source"] == "test.docx"
    # Unmapped keys must be dropped when keep_unmapped=False.
    assert "content" not in sent_payload
    assert "file_name" not in sent_payload
    assert "forge_job_id" not in sent_payload
    assert "domain" not in sent_payload
    assert "metadata" not in sent_payload
    # Only the two mapped target keys should survive.
    assert set(sent_payload.keys()) == {"text", "file_source"}


@pytest.mark.asyncio
async def test_callback_keeps_original_without_map(store, mock_result):
    """With callback_field_map=None, the Cortex-style payload passes through unchanged."""
    config = Config(callback_field_map=None)
    job = await store.create(
        "test.docx", "docx", "extract",
        callback_url="http://cortex/ingest",
    )
    with patch("worker.EXTRACTORS", {"docx": AsyncMock(return_value=mock_result)}):
        with patch("worker.MetaExtractor") as MockMeta:
            mock_meta = AsyncMock()
            mock_meta.extract = AsyncMock(return_value={})
            mock_meta.close = AsyncMock()
            MockMeta.return_value = mock_meta
            with patch("worker._send_callback", new_callable=AsyncMock) as mock_cb:
                await process_job(job, b"fake", "extract", store, config)

    mock_cb.assert_called_once()
    sent_payload = mock_cb.call_args[0][1]
    # Original Cortex keys present and unchanged.
    assert sent_payload["content"] == "# Hello"
    assert sent_payload["file_name"] == "test.docx"
    assert sent_payload["domain"] == "general"
    assert "metadata" in sent_payload
    assert sent_payload["extract"] is True
    assert sent_payload["pre_converted"] is True
    assert sent_payload["forge_job_id"] == job.id
    assert sent_payload["forge_status"] == "completed"


@pytest.mark.asyncio
async def test_callback_renames_and_keeps_unmapped(store, mock_result):
    """keep_unmapped=True: mapped keys renamed, unmapped keys retained."""
    config = Config(
        callback_field_map='{"content":"text"}',
        callback_keep_unmapped=True,
    )
    job = await store.create(
        "test.docx", "docx", "extract",
        callback_url="http://downstream/ingest",
    )
    with patch("worker.EXTRACTORS", {"docx": AsyncMock(return_value=mock_result)}):
        with patch("worker.MetaExtractor") as MockMeta:
            mock_meta = AsyncMock()
            mock_meta.extract = AsyncMock(return_value={})
            mock_meta.close = AsyncMock()
            MockMeta.return_value = mock_meta
            with patch("worker._send_callback", new_callable=AsyncMock) as mock_cb:
                await process_job(job, b"fake", "extract", store, config)

    mock_cb.assert_called_once()
    sent_payload = mock_cb.call_args[0][1]
    # Mapped key renamed: content → text.
    assert "text" in sent_payload
    assert sent_payload["text"] == "# Hello"
    assert "content" not in sent_payload
    # Unmapped keys retained (keep_unmapped=True).
    assert "file_name" in sent_payload
    assert sent_payload["file_name"] == "test.docx"
    assert "forge_job_id" in sent_payload
    assert sent_payload["forge_job_id"] == job.id
    assert "domain" in sent_payload
    assert "metadata" in sent_payload
    assert sent_payload["extract"] is True
    assert sent_payload["pre_converted"] is True
