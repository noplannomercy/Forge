import pytest
from job_store import InMemoryJobStore
from models import JobStatus, ConvertResult, Quality


@pytest.fixture
def store():
    return InMemoryJobStore()


@pytest.mark.asyncio
async def test_create_job(store):
    job = await store.create("test.pdf", "pdf", "vlm")
    assert job.status == JobStatus.QUEUED
    assert job.file_name == "test.pdf"
    assert job.source_format == "pdf"
    assert job.route == "vlm"
    assert job.id  # uuid가 할당됨


@pytest.mark.asyncio
async def test_get_job(store):
    job = await store.create("test.pdf", "pdf", "vlm")
    fetched = await store.get(job.id)
    assert fetched is not None
    assert fetched.id == job.id


@pytest.mark.asyncio
async def test_get_nonexistent_returns_none(store):
    result = await store.get("nonexistent-id")
    assert result is None


@pytest.mark.asyncio
async def test_update_status(store):
    job = await store.create("test.pdf", "pdf", "vlm")
    await store.update_status(job.id, JobStatus.PROCESSING)
    fetched = await store.get(job.id)
    assert fetched.status == JobStatus.PROCESSING


@pytest.mark.asyncio
async def test_save_result(store):
    job = await store.create("test.docx", "docx", "extract")
    quality = Quality(total_chars=100, chars_per_page=100, total_pages=1, failed_pages=0, confidence="high")
    result = ConvertResult(
        text="# Hello", format="md", pages=1,
        file_name="test.docx", source_format="docx",
        route="extract", quality=quality,
    )
    await store.save_result(job.id, result)
    fetched = await store.get(job.id)
    assert fetched.status == JobStatus.COMPLETED
    assert fetched.result.text == "# Hello"
    assert fetched.completed_at is not None


@pytest.mark.asyncio
async def test_save_error(store):
    job = await store.create("bad.xyz", "xyz", "extract")
    await store.save_error(job.id, "UnsupportedFormat: .xyz")
    fetched = await store.get(job.id)
    assert fetched.status == JobStatus.FAILED
    assert fetched.error == "UnsupportedFormat: .xyz"
    assert fetched.completed_at is not None
