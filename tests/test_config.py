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
