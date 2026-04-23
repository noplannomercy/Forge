import pytest
from unittest.mock import AsyncMock
from job_store import PostgresJobStore, VLMLogStore
from models import JobStatus, ConvertResult, Quality


@pytest.fixture
def mock_pool():
    pool = AsyncMock()
    return pool


@pytest.fixture
def store(mock_pool):
    return PostgresJobStore(mock_pool)


@pytest.fixture
def vlm_log_store(mock_pool):
    return VLMLogStore(mock_pool)


@pytest.mark.asyncio
async def test_create_job(store, mock_pool):
    mock_pool.fetchrow = AsyncMock(return_value={
        "id": "test-uuid", "status": "queued", "file_name": "test.pdf",
        "file_size": 1024, "source_format": "pdf", "route": "vlm",
        "method": "semantic", "requested_by": None, "result_text": None,
        "meta": "{}", "quality": "{}", "prompt_version": None,
        "meta_prompt_version": None, "error": None,
        "created_at": "2026-04-07T00:00:00+00:00", "started_at": None,
        "completed_at": None, "processing_ms": None,
    })
    job = await store.create("test.pdf", "pdf", "vlm", file_size=1024, method="semantic")
    assert job.file_name == "test.pdf"
    assert job.route == "vlm"
    mock_pool.fetchrow.assert_called_once()


@pytest.mark.asyncio
async def test_get_job(store, mock_pool):
    mock_pool.fetchrow = AsyncMock(return_value={
        "id": "test-uuid", "status": "queued", "file_name": "test.pdf",
        "file_size": None, "source_format": "pdf", "route": "vlm",
        "method": "extract", "requested_by": None, "result_text": None,
        "meta": "{}", "quality": "{}", "prompt_version": None,
        "meta_prompt_version": None, "error": None,
        "created_at": "2026-04-07T00:00:00+00:00", "started_at": None,
        "completed_at": None, "processing_ms": None,
    })
    job = await store.get("test-uuid")
    assert job is not None
    assert job.id == "test-uuid"


@pytest.mark.asyncio
async def test_get_nonexistent(store, mock_pool):
    mock_pool.fetchrow = AsyncMock(return_value=None)
    job = await store.get("nonexistent")
    assert job is None


@pytest.mark.asyncio
async def test_update_status(store, mock_pool):
    mock_pool.execute = AsyncMock()
    await store.update_status("test-uuid", JobStatus.PROCESSING)
    mock_pool.execute.assert_called_once()


@pytest.mark.asyncio
async def test_save_result(store, mock_pool):
    mock_pool.execute = AsyncMock()
    quality = Quality(total_chars=100, chars_per_page=100, total_pages=1, failed_pages=0, confidence="high", method="semantic")
    result = ConvertResult(
        text="# Hello", format="md", pages=1,
        file_name="test.pdf", source_format="pdf",
        route="vlm", quality=quality,
    )
    await store.save_result("test-uuid", result)
    mock_pool.execute.assert_called_once()


@pytest.mark.asyncio
async def test_save_meta(store, mock_pool):
    mock_pool.execute = AsyncMock()
    await store.save_meta("test-uuid", {"category": "제안서"}, "meta-v1")
    mock_pool.execute.assert_called_once()


@pytest.mark.asyncio
async def test_save_error(store, mock_pool):
    mock_pool.execute = AsyncMock()
    await store.save_error("test-uuid", "conversion failed")
    mock_pool.execute.assert_called_once()


@pytest.mark.asyncio
async def test_vlm_log_insert(vlm_log_store, mock_pool):
    mock_pool.execute = AsyncMock()
    await vlm_log_store.log(
        job_id="test-uuid", batch_num=1, purpose="convert",
        model="gemini-2.0-flash", prompt_version="semantic-v1",
        input_tokens=1000, output_tokens=500, cost_usd=0.0001,
        latency_ms=2500, success=True, error=None,
    )
    mock_pool.execute.assert_called_once()
