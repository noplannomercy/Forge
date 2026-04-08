import pytest
from unittest.mock import AsyncMock
from job_store import PostgresJobStore


@pytest.fixture
def mock_pool():
    return AsyncMock()


@pytest.fixture
def store(mock_pool):
    return PostgresJobStore(mock_pool)


@pytest.mark.asyncio
async def test_list_jobs(store, mock_pool):
    mock_pool.fetchval = AsyncMock(return_value=2)
    mock_pool.fetch = AsyncMock(return_value=[
        {"id": "uuid-1", "file_name": "a.pdf", "status": "completed", "route": "vlm",
         "method": "semantic", "source_format": "pdf", "requested_by": "test",
         "meta": "{}", "processing_ms": 5000, "created_at": "2026-04-08T00:00:00+00:00",
         "deleted_at": None},
        {"id": "uuid-2", "file_name": "b.docx", "status": "completed", "route": "extract",
         "method": "extract", "source_format": "docx", "requested_by": "test",
         "meta": "{}", "processing_ms": 200, "created_at": "2026-04-08T00:00:00+00:00",
         "deleted_at": None},
    ])
    jobs, total = await store.list_jobs(page=1, size=20)
    assert total == 2
    assert len(jobs) == 2


@pytest.mark.asyncio
async def test_list_jobs_with_filters(store, mock_pool):
    mock_pool.fetchval = AsyncMock(return_value=1)
    mock_pool.fetch = AsyncMock(return_value=[
        {"id": "uuid-1", "file_name": "a.pdf", "status": "completed", "route": "vlm",
         "method": "semantic", "source_format": "pdf", "requested_by": "cortex",
         "meta": "{}", "processing_ms": 5000, "created_at": "2026-04-08T00:00:00+00:00",
         "deleted_at": None},
    ])
    jobs, total = await store.list_jobs(page=1, size=20, status="completed", source_format="pdf")
    assert total == 1


@pytest.mark.asyncio
async def test_soft_delete(store, mock_pool):
    mock_pool.execute = AsyncMock(return_value="UPDATE 1")
    result = await store.soft_delete("uuid-1")
    assert result is True


@pytest.mark.asyncio
async def test_soft_delete_not_found(store, mock_pool):
    mock_pool.execute = AsyncMock(return_value="UPDATE 0")
    result = await store.soft_delete("nonexistent")
    assert result is False


@pytest.mark.asyncio
async def test_update_meta_merge(store, mock_pool):
    mock_pool.fetchval = AsyncMock(return_value='{"category": "제안서", "title": "기존"}')
    mock_pool.execute = AsyncMock()
    merged = await store.update_meta("uuid-1", {"category": "수정됨"})
    assert merged["category"] == "수정됨"
    assert merged["title"] == "기존"


@pytest.mark.asyncio
async def test_stats_daily(store, mock_pool):
    mock_pool.fetch = AsyncMock(return_value=[
        {"day": "2026-04-07", "total": 10, "success": 8, "failed": 2, "avg_ms": 5000.0},
    ])
    stats = await store.stats_daily("2026-04-01", "2026-04-08")
    assert len(stats) == 1
    assert stats[0]["total"] == 10


@pytest.mark.asyncio
async def test_stats_cost(store, mock_pool):
    mock_pool.fetch = AsyncMock(return_value=[
        {"day": "2026-04-07", "total_cost_usd": 0.05, "total_tokens": 15000},
    ])
    stats = await store.stats_cost("2026-04-01", "2026-04-08")
    assert len(stats) == 1


@pytest.mark.asyncio
async def test_stats_models(store, mock_pool):
    mock_pool.fetch = AsyncMock(return_value=[
        {"model": "gemini-2.0-flash", "calls": 50, "avg_latency_ms": 3000.0,
         "total_cost_usd": 0.03, "total_input_tokens": 10000, "total_output_tokens": 5000},
    ])
    stats = await store.stats_models()
    assert len(stats) == 1
    assert stats[0]["model"] == "gemini-2.0-flash"
