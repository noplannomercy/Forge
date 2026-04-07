import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from worker import process_job
from job_store import InMemoryJobStore
from models import JobStatus, ConvertResult, Quality, DocumentResult
from config import Config


@pytest.fixture
def store():
    return InMemoryJobStore()


@pytest.fixture
def config():
    return Config()


@pytest.mark.asyncio
async def test_worker_extract_route(store, config):
    """extract 경로 — extractor 호출 → 결과 저장"""
    job = await store.create("test.docx", "docx", "extract")

    mock_result = ConvertResult(
        text="# Hello",
        format="md",
        pages=1,
        file_name="test.docx",
        source_format="docx",
        route="extract",
        quality=Quality(total_chars=7, chars_per_page=7, total_pages=1, failed_pages=0, confidence="high", method="extract"),
    )

    with patch("worker.EXTRACTORS", {"docx": AsyncMock(return_value=mock_result)}):
        await process_job(job, b"fake_docx_bytes", "extract", store, config)

    updated = await store.get(job.id)
    assert updated.status == JobStatus.COMPLETED
    assert updated.result.text == "# Hello"
    assert updated.result.quality.method == "extract"


@pytest.mark.asyncio
async def test_worker_vlm_pdf_route(store, config):
    """vlm 경로 — PDF → images → semantic VLM"""
    job = await store.create("scan.pdf", "pdf", "vlm")

    mock_doc_result = DocumentResult(
        text="# Scanned", total_pages=5, failed_pages=0,
        confidence="high", total_batches=1, failed_batches=0,
    )

    with patch("worker.pdf_to_images", new_callable=AsyncMock, return_value=[b"img"] * 5):
        with patch("worker.VLMClient") as MockVLM:
            mock_instance = AsyncMock()
            mock_instance.process_document = AsyncMock(return_value=mock_doc_result)
            mock_instance.close = AsyncMock()
            MockVLM.return_value = mock_instance
            await process_job(job, b"fake_pdf_bytes", "vlm", store, config)

    updated = await store.get(job.id)
    assert updated.status == JobStatus.COMPLETED
    assert updated.result.quality.method == "semantic"
    assert updated.result.quality.total_batches == 1


@pytest.mark.asyncio
async def test_worker_vlm_pptx_route(store, config):
    """vlm 경로 — PPTX → LibreOffice → PDF → images → semantic VLM"""
    job = await store.create("slides.pptx", "pptx", "vlm")

    mock_doc_result = DocumentResult(
        text="# Slides", total_pages=3, failed_pages=0,
        confidence="high", total_batches=1, failed_batches=0,
    )

    with patch("worker.pptx_to_pdf", new_callable=AsyncMock, return_value=b"fake_pdf"):
        with patch("worker.pdf_to_images", new_callable=AsyncMock, return_value=[b"img"] * 3):
            with patch("worker.VLMClient") as MockVLM:
                mock_instance = AsyncMock()
                mock_instance.process_document = AsyncMock(return_value=mock_doc_result)
                mock_instance.close = AsyncMock()
                MockVLM.return_value = mock_instance
                await process_job(job, b"fake_pptx_bytes", "vlm", store, config)

    updated = await store.get(job.id)
    assert updated.status == JobStatus.COMPLETED
    assert updated.result.text == "# Slides"
    assert updated.result.quality.method == "semantic"


@pytest.mark.asyncio
async def test_worker_vlm_image_route(store, config):
    """vlm 경로 — 이미지 단건"""
    job = await store.create("photo.jpg", "jpg", "vlm")

    mock_doc_result = DocumentResult(
        text="# Photo", total_pages=1, failed_pages=0,
        confidence="high", total_batches=1, failed_batches=0,
    )

    with patch("worker.prepare_image", new_callable=AsyncMock, return_value=b"png_bytes"):
        with patch("worker.VLMClient") as MockVLM:
            mock_instance = AsyncMock()
            mock_instance.process_document = AsyncMock(return_value=mock_doc_result)
            mock_instance.close = AsyncMock()
            MockVLM.return_value = mock_instance
            await process_job(job, b"fake_jpg_bytes", "vlm", store, config)

    updated = await store.get(job.id)
    assert updated.status == JobStatus.COMPLETED
    assert updated.result.quality.method == "semantic"


@pytest.mark.asyncio
async def test_worker_handles_error(store, config):
    """extractor 예외 시 job이 failed로 전환"""
    job = await store.create("bad.docx", "docx", "extract")

    with patch("worker.EXTRACTORS", {"docx": AsyncMock(side_effect=Exception("corrupt file"))}):
        await process_job(job, b"bad_bytes", "extract", store, config)

    updated = await store.get(job.id)
    assert updated.status == JobStatus.FAILED
    assert "corrupt file" in updated.error
