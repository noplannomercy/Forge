import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from vlm import VLMClient
from config import Config


@pytest.fixture
def vlm_config():
    return Config(
        vlm_url="http://localhost:11434/v1/chat/completions",
        vlm_model="test-model",
        vlm_timeout=10,
        vlm_concurrency=2,
    )


@pytest.fixture
def vlm_client(vlm_config):
    return VLMClient(vlm_config)


@pytest.mark.asyncio
async def test_process_page_success(vlm_client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "# Extracted Text"}}]
    }
    mock_response.raise_for_status = MagicMock()

    with patch.object(vlm_client.client, "post", new_callable=AsyncMock, return_value=mock_response):
        result = await vlm_client.process_page(b"fake_image", 1)

    assert result.success is True
    assert result.text == "# Extracted Text"
    assert result.page == 1
    assert result.error is None


@pytest.mark.asyncio
async def test_process_page_failure(vlm_client):
    with patch.object(vlm_client.client, "post", new_callable=AsyncMock, side_effect=Exception("connection refused")):
        with patch("vlm.asyncio.sleep", new_callable=AsyncMock):  # skip retry delays
            result = await vlm_client.process_page(b"fake_image", 3)

    assert result.success is False
    assert "[변환 실패: 페이지 3]" in result.text
    assert "connection refused" in result.error


@pytest.mark.asyncio
async def test_process_document_all_success(vlm_client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "page text"}}]
    }
    mock_response.raise_for_status = MagicMock()

    with patch.object(vlm_client.client, "post", new_callable=AsyncMock, return_value=mock_response):
        result = await vlm_client.process_document([b"img1", b"img2"])

    assert result.total_pages == 2
    assert result.failed_pages == 0
    assert result.confidence == "high"
    assert "page text" in result.text


@pytest.mark.asyncio
async def test_process_document_partial_failure(vlm_client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "page text"}}]
    }
    mock_response.raise_for_status = MagicMock()

    call_count = 0

    async def mock_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        # Fail all attempts for page 2 (calls 4,5,6 in retry sequence)
        # Page 1: calls 1 (success), Page 2: calls 2,3,4 (all fail), Page 3: call 5 (success)
        if call_count in (2, 3, 4):
            raise Exception("timeout")
        return mock_response

    with patch.object(vlm_client.client, "post", side_effect=mock_post):
        with patch("vlm.asyncio.sleep", new_callable=AsyncMock):
            result = await vlm_client.process_document([b"img1", b"img2", b"img3"])

    assert result.total_pages == 3
    assert result.failed_pages == 1
    assert result.confidence == "partial"
    assert "[변환 실패: 페이지 2]" in result.text


@pytest.mark.asyncio
async def test_semaphore_limits_concurrency(vlm_client):
    """동시 실행이 vlm_concurrency(2)로 제한되는지 확인"""
    active = 0
    max_active = 0

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "text"}}]
    }
    mock_response.raise_for_status = MagicMock()

    async def tracking_post(*args, **kwargs):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.05)
        active -= 1
        return mock_response

    with patch.object(vlm_client.client, "post", side_effect=tracking_post):
        await vlm_client.process_document([b"img"] * 5)

    assert max_active <= 2  # vlm_concurrency = 2


@pytest.mark.asyncio
async def test_vlm_client_close(vlm_client):
    await vlm_client.close()


@pytest.mark.asyncio
async def test_retry_then_success(vlm_client):
    """2회 실패 후 3회째 성공"""
    call_count = 0
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
    mock_response.raise_for_status = MagicMock()

    async def flaky_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise Exception("timeout")
        return mock_response

    with patch.object(vlm_client.client, "post", side_effect=flaky_post):
        with patch("vlm.asyncio.sleep", new_callable=AsyncMock):
            result = await vlm_client.process_page(b"img", 1)
    assert result.success is True
    assert call_count == 3


@pytest.mark.asyncio
async def test_retry_all_fail(vlm_client):
    """3회 모두 실패"""
    with patch.object(vlm_client.client, "post", new_callable=AsyncMock, side_effect=Exception("down")):
        with patch("vlm.asyncio.sleep", new_callable=AsyncMock):
            result = await vlm_client.process_page(b"img", 1)
    assert result.success is False
    assert "[변환 실패: 페이지 1]" in result.text
