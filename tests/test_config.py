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
