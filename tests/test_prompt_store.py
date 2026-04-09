import pytest
from unittest.mock import AsyncMock
from job_store import PromptStore


@pytest.fixture
def mock_pool():
    return AsyncMock()


@pytest.fixture
def store(mock_pool):
    return PromptStore(mock_pool)


@pytest.mark.asyncio
async def test_get_active(store, mock_pool):
    mock_pool.fetchrow = AsyncMock(return_value={
        "id": 1, "type": "semantic", "version": 1,
        "text": "prompt text", "is_active": True,
        "created_at": "2026-04-09T00:00:00+00:00",
    })
    result = await store.get_active("semantic")
    assert result["type"] == "semantic"
    assert result["text"] == "prompt text"


@pytest.mark.asyncio
async def test_get_active_not_found(store, mock_pool):
    mock_pool.fetchrow = AsyncMock(return_value=None)
    result = await store.get_active("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_list_all(store, mock_pool):
    mock_pool.fetch = AsyncMock(return_value=[
        {"id": 2, "type": "semantic", "version": 2, "text": "v2", "is_active": True, "created_at": "2026-04-09"},
        {"id": 1, "type": "semantic", "version": 1, "text": "v1", "is_active": False, "created_at": "2026-04-08"},
    ])
    result = await store.list_all()
    assert len(result) == 2


@pytest.mark.asyncio
async def test_create_version(store, mock_pool):
    mock_pool.fetchval = AsyncMock(return_value=1)
    mock_pool.execute = AsyncMock()
    mock_pool.fetchrow = AsyncMock(return_value={
        "id": 2, "type": "semantic", "version": 2,
        "text": "new prompt", "is_active": True,
        "created_at": "2026-04-09T00:00:00+00:00",
    })
    result = await store.create_version("semantic", "new prompt")
    assert result["version"] == 2
    assert result["is_active"] is True


@pytest.mark.asyncio
async def test_create_version_first(store, mock_pool):
    mock_pool.fetchval = AsyncMock(return_value=None)
    mock_pool.execute = AsyncMock()
    mock_pool.fetchrow = AsyncMock(return_value={
        "id": 1, "type": "meta_extract", "version": 1,
        "text": "first prompt", "is_active": True,
        "created_at": "2026-04-09T00:00:00+00:00",
    })
    result = await store.create_version("meta_extract", "first prompt")
    assert result["version"] == 1
