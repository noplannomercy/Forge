import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from meta import MetaExtractor
from config import Config


@pytest.fixture
def config():
    return Config(
        vlm_url="http://localhost/v1/chat/completions",
        vlm_model="gemini-2.0-flash",
        vlm_api_key="test-key",
    )


@pytest.fixture
def extractor(config):
    return MetaExtractor(config)


@pytest.mark.asyncio
async def test_extract_meta_success(extractor):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": '{"category": "제안서", "title": "테스트", "summary": "요약", "keywords": ["a","b","c","d","e"]}'}}]
    }
    mock_response.raise_for_status = MagicMock()

    with patch.object(extractor.client, "post", new_callable=AsyncMock, return_value=mock_response):
        meta = await extractor.extract("# 테스트 문서 내용")

    assert meta["category"] == "제안서"
    assert meta["title"] == "테스트"
    assert len(meta["keywords"]) == 5


@pytest.mark.asyncio
async def test_extract_meta_truncates_long_text(extractor):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": '{"category": "보고서", "title": "긴문서", "summary": "요약", "keywords": ["a","b","c","d","e"]}'}}]
    }
    mock_response.raise_for_status = MagicMock()

    long_text = "x" * 10000
    with patch.object(extractor.client, "post", new_callable=AsyncMock, return_value=mock_response) as mock_post:
        meta = await extractor.extract(long_text)

    # Verify the text was truncated in the payload
    call_args = mock_post.call_args
    payload = call_args[1]["json"]
    message_content = payload["messages"][0]["content"]
    assert len(message_content) < 5000


@pytest.mark.asyncio
async def test_extract_meta_failure_returns_empty(extractor):
    with patch.object(extractor.client, "post", new_callable=AsyncMock, side_effect=Exception("timeout")):
        meta = await extractor.extract("# 문서 내용")
    assert meta == {}


@pytest.mark.asyncio
async def test_extract_meta_invalid_json_returns_empty(extractor):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "이것은 JSON이 아닙니다"}}]
    }
    mock_response.raise_for_status = MagicMock()

    with patch.object(extractor.client, "post", new_callable=AsyncMock, return_value=mock_response):
        meta = await extractor.extract("# 문서 내용")
    assert meta == {}


@pytest.mark.asyncio
async def test_meta_extractor_uses_fallback_config():
    config = Config(
        vlm_url="http://vlm-server/v1/chat/completions",
        vlm_model="gemini-flash",
        vlm_api_key="vlm-key",
        meta_llm_url="",
        meta_llm_model="",
        meta_llm_api_key="",
    )
    extractor = MetaExtractor(config)
    assert extractor.url == "http://vlm-server/v1/chat/completions"
    assert extractor.model == "gemini-flash"


@pytest.mark.asyncio
async def test_meta_extractor_uses_dedicated_config():
    config = Config(
        vlm_url="http://vlm-server/v1/chat/completions",
        vlm_model="gemini-flash",
        meta_llm_url="http://meta-server/v1/chat/completions",
        meta_llm_model="haiku",
        meta_llm_api_key="meta-key",
    )
    extractor = MetaExtractor(config)
    assert extractor.url == "http://meta-server/v1/chat/completions"
    assert extractor.model == "haiku"


@pytest.mark.asyncio
async def test_meta_extractor_close(extractor):
    await extractor.close()
