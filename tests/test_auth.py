import pytest
from unittest.mock import MagicMock
from fastapi import HTTPException
from auth import verify_api_key


def test_verify_api_key_valid():
    config = MagicMock()
    config.forge_api_key = "secret-123"
    dep = verify_api_key(config)
    result = dep("secret-123")
    assert result is None


def test_verify_api_key_invalid():
    config = MagicMock()
    config.forge_api_key = "secret-123"
    dep = verify_api_key(config)
    with pytest.raises(HTTPException) as exc_info:
        dep("wrong-key")
    assert exc_info.value.status_code == 401


def test_verify_api_key_missing():
    config = MagicMock()
    config.forge_api_key = "secret-123"
    dep = verify_api_key(config)
    with pytest.raises(HTTPException) as exc_info:
        dep(None)
    assert exc_info.value.status_code == 401


def test_verify_api_key_disabled():
    config = MagicMock()
    config.forge_api_key = ""
    dep = verify_api_key(config)
    result = dep(None)
    assert result is None
