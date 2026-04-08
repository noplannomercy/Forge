import pytest
import asyncio
from unittest.mock import patch, AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport
from app import create_app
from config import Config


@pytest.fixture
def app():
    config = Config(forge_api_key="test-key")
    return create_app(config=config)


@pytest.fixture
def app_no_auth():
    config = Config(forge_api_key="")
    return create_app(config=config)


@pytest.mark.asyncio
async def test_admin_requires_auth(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/jobs/some-id")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_admin_valid_auth(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/jobs/nonexistent", headers={"X-Forge-Key": "test-key"})
    # Should be 404 (not found), not 401
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_admin_no_auth_when_disabled(app_no_auth):
    transport = ASGITransport(app=app_no_auth)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/jobs/nonexistent")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_job(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch("app.process_job", new_callable=AsyncMock):
            create_resp = await client.post(
                "/convert",
                files={"file": ("test.docx", b"content", "application/octet-stream")},
            )
        job_id = create_resp.json()["job_id"]
        resp = await client.delete(f"/jobs/{job_id}", headers={"X-Forge-Key": "test-key"})
    assert resp.status_code == 200
    assert resp.json()["deleted"] is True


@pytest.mark.asyncio
async def test_delete_nonexistent(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.delete("/jobs/nonexistent-id", headers={"X-Forge-Key": "test-key"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_patch_meta(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch("app.process_job", new_callable=AsyncMock):
            create_resp = await client.post(
                "/convert",
                files={"file": ("test.docx", b"content", "application/octet-stream")},
            )
        job_id = create_resp.json()["job_id"]
        resp = await client.patch(
            f"/jobs/{job_id}/meta",
            json={"category": "수정됨"},
            headers={"X-Forge-Key": "test-key"},
        )
    assert resp.status_code == 200
    assert resp.json()["meta"]["category"] == "수정됨"


@pytest.mark.asyncio
async def test_retry_no_result(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch("app.process_job", new_callable=AsyncMock):
            create_resp = await client.post(
                "/convert",
                files={"file": ("test.docx", b"content", "application/octet-stream")},
            )
        job_id = create_resp.json()["job_id"]
        resp = await client.post(f"/jobs/{job_id}/retry", headers={"X-Forge-Key": "test-key"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_existing_endpoints_no_auth(app):
    """기존 /health, /convert 등은 인증 불필요"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
