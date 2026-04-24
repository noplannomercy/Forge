import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from worker import process_job
from models import JobStatus, ConvertResult, Quality, DocumentResult
from config import Config


@pytest.fixture
def config():
    return Config()


@pytest.mark.asyncio
async def test_worker_extract_route(store, config):
    job = await store.create("test.docx", "docx", "extract")
    mock_result = ConvertResult(
        text="# Hello", format="md", pages=1, file_name="test.docx",
        source_format="docx", route="extract",
        quality=Quality(total_chars=7, chars_per_page=7, total_pages=1, failed_pages=0, confidence="high", method="extract"),
    )
    with patch("worker.EXTRACTORS", {"docx": AsyncMock(return_value=mock_result)}):
        with patch("worker.MetaExtractor") as MockMeta:
            mock_meta = AsyncMock()
            mock_meta.extract = AsyncMock(return_value={"category": "문서"})
            mock_meta.close = AsyncMock()
            MockMeta.return_value = mock_meta
            await process_job(job, b"fake_docx_bytes", "extract", store, config)
    updated = await store.get(job.id)
    assert updated.status == JobStatus.COMPLETED
    assert updated.result.text == "# Hello"


@pytest.mark.asyncio
async def test_worker_vlm_pdf_route(store, config):
    job = await store.create("scan.pdf", "pdf", "vlm")
    mock_doc_result = DocumentResult(
        text="# Scanned", total_pages=5, failed_pages=0,
        confidence="high", total_batches=1, failed_batches=0,
    )
    with patch("worker.pdf_to_images", new_callable=AsyncMock, return_value=[b"img"] * 5):
        with patch("worker.VLMClient") as MockVLM:
            mock_vlm = AsyncMock()
            mock_vlm.process_document = AsyncMock(return_value=(mock_doc_result, []))
            mock_vlm.close = AsyncMock()
            MockVLM.return_value = mock_vlm
            with patch("worker.MetaExtractor") as MockMeta:
                mock_meta = AsyncMock()
                mock_meta.extract = AsyncMock(return_value={})
                mock_meta.close = AsyncMock()
                MockMeta.return_value = mock_meta
                await process_job(job, b"fake_pdf_bytes", "vlm", store, config)
    updated = await store.get(job.id)
    assert updated.status == JobStatus.COMPLETED
    assert updated.result.quality.method == "semantic"


@pytest.mark.asyncio
async def test_worker_vlm_pptx_route(store, config):
    job = await store.create("slides.pptx", "pptx", "vlm")
    mock_doc_result = DocumentResult(
        text="# Slides", total_pages=3, failed_pages=0,
        confidence="high", total_batches=1, failed_batches=0,
    )
    with patch("worker.pptx_to_pdf", new_callable=AsyncMock, return_value=b"fake_pdf"):
        with patch("worker.pdf_to_images", new_callable=AsyncMock, return_value=[b"img"] * 3):
            with patch("worker.VLMClient") as MockVLM:
                mock_vlm = AsyncMock()
                mock_vlm.process_document = AsyncMock(return_value=(mock_doc_result, []))
                mock_vlm.close = AsyncMock()
                MockVLM.return_value = mock_vlm
                with patch("worker.MetaExtractor") as MockMeta:
                    mock_meta = AsyncMock()
                    mock_meta.extract = AsyncMock(return_value={})
                    mock_meta.close = AsyncMock()
                    MockMeta.return_value = mock_meta
                    await process_job(job, b"fake_pptx_bytes", "vlm", store, config)
    updated = await store.get(job.id)
    assert updated.status == JobStatus.COMPLETED
    assert updated.result.text == "# Slides"


@pytest.mark.asyncio
async def test_worker_vlm_image_route(store, config):
    job = await store.create("photo.jpg", "jpg", "vlm")
    mock_doc_result = DocumentResult(
        text="# Photo", total_pages=1, failed_pages=0,
        confidence="high", total_batches=1, failed_batches=0,
    )
    with patch("worker.prepare_image", new_callable=AsyncMock, return_value=b"png_bytes"):
        with patch("worker.VLMClient") as MockVLM:
            mock_vlm = AsyncMock()
            mock_vlm.process_document = AsyncMock(return_value=(mock_doc_result, []))
            mock_vlm.close = AsyncMock()
            MockVLM.return_value = mock_vlm
            with patch("worker.MetaExtractor") as MockMeta:
                mock_meta = AsyncMock()
                mock_meta.extract = AsyncMock(return_value={})
                mock_meta.close = AsyncMock()
                MockMeta.return_value = mock_meta
                await process_job(job, b"fake_jpg_bytes", "vlm", store, config)
    updated = await store.get(job.id)
    assert updated.status == JobStatus.COMPLETED


@pytest.mark.asyncio
async def test_worker_handles_error(store, config):
    job = await store.create("bad.docx", "docx", "extract")
    with patch("worker.EXTRACTORS", {"docx": AsyncMock(side_effect=Exception("corrupt file"))}):
        await process_job(job, b"bad_bytes", "extract", store, config)
    updated = await store.get(job.id)
    assert updated.status == JobStatus.FAILED
    assert "corrupt file" in updated.error


@pytest.mark.asyncio
async def test_worker_vlm_calls_meta_extraction(store, config):
    job = await store.create("scan.pdf", "pdf", "vlm")
    mock_doc_result = DocumentResult(
        text="# Scanned", total_pages=1, failed_pages=0,
        confidence="high", total_batches=1, failed_batches=0,
    )
    with patch("worker.pdf_to_images", new_callable=AsyncMock, return_value=[b"img"]):
        with patch("worker.VLMClient") as MockVLM:
            mock_vlm = AsyncMock()
            mock_vlm.process_document = AsyncMock(return_value=(mock_doc_result, []))
            mock_vlm.close = AsyncMock()
            MockVLM.return_value = mock_vlm
            with patch("worker.MetaExtractor") as MockMeta:
                mock_meta = AsyncMock()
                mock_meta.extract = AsyncMock(return_value={"category": "보고서"})
                mock_meta.close = AsyncMock()
                MockMeta.return_value = mock_meta
                await process_job(job, b"fake", "vlm", store, config)
    updated = await store.get(job.id)
    assert updated.status == JobStatus.COMPLETED
    mock_meta.extract.assert_called_once()


@pytest.mark.asyncio
async def test_worker_meta_failure_doesnt_fail_job(store, config):
    job = await store.create("scan.pdf", "pdf", "vlm")
    mock_doc_result = DocumentResult(
        text="# Scanned", total_pages=1, failed_pages=0,
        confidence="high", total_batches=1, failed_batches=0,
    )
    with patch("worker.pdf_to_images", new_callable=AsyncMock, return_value=[b"img"]):
        with patch("worker.VLMClient") as MockVLM:
            mock_vlm = AsyncMock()
            mock_vlm.process_document = AsyncMock(return_value=(mock_doc_result, []))
            mock_vlm.close = AsyncMock()
            MockVLM.return_value = mock_vlm
            with patch("worker.MetaExtractor") as MockMeta:
                mock_meta = AsyncMock()
                mock_meta.extract = AsyncMock(side_effect=Exception("LLM down"))
                mock_meta.close = AsyncMock()
                MockMeta.return_value = mock_meta
                await process_job(job, b"fake", "vlm", store, config)
    updated = await store.get(job.id)
    assert updated.status == JobStatus.COMPLETED


@pytest.mark.asyncio
async def test_worker_extract_calls_meta_extraction(store, config):
    job = await store.create("test.docx", "docx", "extract")
    mock_result = ConvertResult(
        text="# Hello", format="md", pages=1, file_name="test.docx",
        source_format="docx", route="extract",
        quality=Quality(total_chars=7, chars_per_page=7, total_pages=1,
                       failed_pages=0, confidence="high", method="extract"),
    )
    with patch("worker.EXTRACTORS", {"docx": AsyncMock(return_value=mock_result)}):
        with patch("worker.MetaExtractor") as MockMeta:
            mock_meta = AsyncMock()
            mock_meta.extract = AsyncMock(return_value={"category": "문서"})
            mock_meta.close = AsyncMock()
            MockMeta.return_value = mock_meta
            await process_job(job, b"fake", "extract", store, config)
    mock_meta.extract.assert_called_once()


@pytest.mark.asyncio
async def test_worker_calls_callback_on_success(store, config):
    job = await store.create("test.docx", "docx", "extract", callback_url="http://cortex/ingest")
    mock_result = ConvertResult(
        text="# Hello", format="md", pages=1, file_name="test.docx",
        source_format="docx", route="extract",
        quality=Quality(total_chars=7, chars_per_page=7, total_pages=1,
                       failed_pages=0, confidence="high", method="extract"),
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
    call_args = mock_cb.call_args
    assert call_args[0][0] == "http://cortex/ingest"
    assert call_args[0][1]["content"] == "# Hello"
    assert call_args[0][1]["file_name"] == "test.docx"
    assert call_args[0][1]["forge_status"] == "completed"


@pytest.mark.asyncio
async def test_worker_calls_callback_on_failure(store, config):
    job = await store.create("bad.docx", "docx", "extract", callback_url="http://cortex/ingest")
    with patch("worker.EXTRACTORS", {"docx": AsyncMock(side_effect=Exception("corrupt"))}):
        with patch("worker._send_callback", new_callable=AsyncMock) as mock_cb:
            await process_job(job, b"bad", "extract", store, config)
    mock_cb.assert_called_once()
    call_args = mock_cb.call_args
    assert call_args[0][1]["forge_status"] == "failed"
    assert "corrupt" in call_args[0][1]["forge_error"]


@pytest.mark.asyncio
async def test_worker_docling_route_calls_extractor(store, config):
    """T14: route='docling' → extractors.docling_ex.extract 호출 + result 저장."""
    job = await store.create("test.pdf", "pdf", "docling")
    mock_result = ConvertResult(
        text="# Mocked docling output",
        format="md",
        pages=1,
        file_name="test.pdf",
        source_format="pdf",
        route="docling",
        quality=Quality(
            total_chars=24, chars_per_page=24, total_pages=1,
            failed_pages=0, confidence="high", method="docling",
        ),
    )
    mock_extract = AsyncMock(return_value=mock_result)
    with patch("extractors.docling_ex.extract", mock_extract):
        with patch("worker.MetaExtractor") as MockMeta:
            mock_meta = AsyncMock()
            mock_meta.extract = AsyncMock(return_value={"category": "문서"})
            mock_meta.close = AsyncMock()
            MockMeta.return_value = mock_meta
            await process_job(job, b"%PDF-fake", "docling", store, config)
    mock_extract.assert_called_once()
    updated = await store.get(job.id)
    assert updated.status == JobStatus.COMPLETED
    assert updated.result.text == "# Mocked docling output"
    assert updated.result.quality.method == "docling"


@pytest.mark.asyncio
async def test_worker_docling_route_threads_log_store(store, config):
    """T14: docling_log_store kwarg가 extractor에 그대로 전달된다."""
    job = await store.create("test.pdf", "pdf", "docling")
    mock_result = ConvertResult(
        text="# md", format="md", pages=1, file_name="test.pdf",
        source_format="pdf", route="docling",
        quality=Quality(
            total_chars=4, chars_per_page=4, total_pages=1,
            failed_pages=0, confidence="high", method="docling",
        ),
    )
    mock_extract = AsyncMock(return_value=mock_result)
    sentinel_log_store = MagicMock()
    with patch("extractors.docling_ex.extract", mock_extract):
        with patch("worker.MetaExtractor") as MockMeta:
            mock_meta = AsyncMock()
            mock_meta.extract = AsyncMock(return_value={})
            mock_meta.close = AsyncMock()
            MockMeta.return_value = mock_meta
            await process_job(
                job, b"%PDF", "docling", store, config,
                docling_log_store=sentinel_log_store,
            )
    kwargs = mock_extract.call_args.kwargs
    assert kwargs["docling_log_store"] is sentinel_log_store
    assert kwargs["job_id"] == job.id
    assert kwargs["config"] is config


@pytest.mark.asyncio
async def test_worker_docling_calls_meta_extraction(store, config):
    """T14: docling 경로도 extract/vlm과 동일하게 meta 추출을 수행한다."""
    job = await store.create("report.pdf", "pdf", "docling")
    mock_result = ConvertResult(
        text="# md", format="md", pages=1, file_name="report.pdf",
        source_format="pdf", route="docling",
        quality=Quality(
            total_chars=4, chars_per_page=4, total_pages=1,
            failed_pages=0, confidence="high", method="docling",
        ),
    )
    mock_extract = AsyncMock(return_value=mock_result)
    with patch("extractors.docling_ex.extract", mock_extract):
        with patch("worker.MetaExtractor") as MockMeta:
            mock_meta = AsyncMock()
            mock_meta.extract = AsyncMock(return_value={"category": "보고서"})
            mock_meta.close = AsyncMock()
            MockMeta.return_value = mock_meta
            await process_job(job, b"%PDF", "docling", store, config)
    mock_meta.extract.assert_called_once()


@pytest.mark.asyncio
async def test_worker_no_callback_when_url_missing(store, config):
    job = await store.create("test.docx", "docx", "extract")
    mock_result = ConvertResult(
        text="# Hello", format="md", pages=1, file_name="test.docx",
        source_format="docx", route="extract",
        quality=Quality(total_chars=7, chars_per_page=7, total_pages=1,
                       failed_pages=0, confidence="high", method="extract"),
    )
    with patch("worker.EXTRACTORS", {"docx": AsyncMock(return_value=mock_result)}):
        with patch("worker.MetaExtractor") as MockMeta:
            mock_meta = AsyncMock()
            mock_meta.extract = AsyncMock(return_value={})
            mock_meta.close = AsyncMock()
            MockMeta.return_value = mock_meta
            with patch("worker._send_callback", new_callable=AsyncMock) as mock_cb:
                await process_job(job, b"fake", "extract", store, config)
    mock_cb.assert_not_called()
