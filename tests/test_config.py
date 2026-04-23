import os
import pytest
from config import Config


def test_config_defaults():
    config = Config()
    assert config.vlm_url == "http://localhost:11434/v1/chat/completions"
    assert config.vlm_model == "qwen2-vl:7b"
    assert config.vlm_api_key == ""
    assert config.vlm_timeout == 120
    assert config.vlm_concurrency == 3
    assert config.host == "0.0.0.0"
    assert config.port == 8003


def test_config_from_env(monkeypatch):
    monkeypatch.setenv("VLM_URL", "http://custom:8080/v1/chat/completions")
    monkeypatch.setenv("VLM_MODEL", "gpt-4o")
    monkeypatch.setenv("VLM_TIMEOUT", "60")
    monkeypatch.setenv("VLM_CONCURRENCY", "5")
    config = Config()
    assert config.vlm_url == "http://custom:8080/v1/chat/completions"
    assert config.vlm_model == "gpt-4o"
    assert config.vlm_timeout == 60
    assert config.vlm_concurrency == 5


def test_config_vlm_batch_size_default():
    config = Config()
    assert config.vlm_batch_size == 5


def test_config_vlm_batch_size_from_env(monkeypatch):
    monkeypatch.setenv("VLM_BATCH_SIZE", "10")
    config = Config()
    assert config.vlm_batch_size == 10


def test_config_database_url_default():
    config = Config()
    assert config.database_url == ""


def test_config_database_url_from_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/forge")
    config = Config()
    assert config.database_url == "postgresql://user:pass@localhost/forge"


def test_config_meta_llm_fallback():
    """META_LLM 미설정 시 빈 문자열 (VLM fallback은 런타임에서 처리)"""
    config = Config()
    assert config.meta_llm_url == ""
    assert config.meta_llm_model == ""
    assert config.meta_llm_api_key == ""


def test_config_forge_api_key_default():
    config = Config()
    assert config.forge_api_key == ""


def test_config_forge_api_key_from_env(monkeypatch):
    monkeypatch.setenv("FORGE_API_KEY", "my-secret-key")
    config = Config()
    assert config.forge_api_key == "my-secret-key"


def test_config_callback_field_map_none_default():
    """미설정 시 None."""
    config = Config(callback_field_map=None)
    assert config.callback_field_map is None


def test_config_callback_field_map_empty_string_normalized_to_none():
    """빈 문자열은 None으로 정규화."""
    config = Config(callback_field_map="")
    assert config.callback_field_map is None


def test_config_callback_field_map_valid_json_object():
    """유효한 string→string JSON object는 통과."""
    raw = '{"content":"text","file_name":"file_source"}'
    config = Config(callback_field_map=raw)
    assert config.callback_field_map == raw


def test_config_rejects_malformed_callback_field_map():
    """잘못된 JSON은 시동 시점에 ValueError."""
    with pytest.raises(ValueError, match="CALLBACK_FIELD_MAP"):
        Config(callback_field_map="{not-json")


def test_config_rejects_non_dict_callback_field_map():
    """JSON array는 거부 (dict만 허용)."""
    with pytest.raises(ValueError, match="CALLBACK_FIELD_MAP"):
        Config(callback_field_map='["a", "b"]')


def test_config_rejects_non_string_values_callback_field_map():
    """value가 문자열이 아니면 거부."""
    with pytest.raises(ValueError, match="CALLBACK_FIELD_MAP"):
        Config(callback_field_map='{"content": 123}')
