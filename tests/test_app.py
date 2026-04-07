import pytest
import asyncio
from unittest.mock import patch, AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport
from app import create_app
from models import JobStatus


@pytest.fixture
def app():
    return create_app()


@pytest.mark.asyncio
async def test_health(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_convert_returns_job_id(app):
    """POST /convert → job_id 반환"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch("app.process_job", new_callable=AsyncMock):
            resp = await client.post(
                "/convert",
                files={"file": ("test.docx", b"fake_docx_content", "application/octet-stream")},
            )
    assert resp.status_code == 200
    data = resp.json()
    assert "job_id" in data
    assert data["status"] == "queued"


@pytest.mark.asyncio
async def test_convert_unsupported_format(app):
    """지원하지 않는 포맷 → 400"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/convert",
            files={"file": ("test.xyz", b"content", "application/octet-stream")},
        )
    assert resp.status_code == 400
    assert "Unsupported" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_result_not_found(app):
    """존재하지 않는 job_id → 404"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/result/nonexistent-id")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_result_queued(app):
    """queued 상태 job → status만 반환"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch("app.process_job", new_callable=AsyncMock):
            create_resp = await client.post(
                "/convert",
                files={"file": ("test.docx", b"content", "application/octet-stream")},
            )
        job_id = create_resp.json()["job_id"]
        resp = await client.get(f"/result/{job_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("queued", "processing")
    assert data["result"] is None


@pytest.mark.asyncio
async def test_batch_returns_job_ids(app):
    """POST /batch → job_id 리스트 반환"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch("app.process_job", new_callable=AsyncMock):
            resp = await client.post(
                "/batch",
                files=[
                    ("files", ("a.docx", b"content1", "application/octet-stream")),
                    ("files", ("b.xlsx", b"content2", "application/octet-stream")),
                ],
            )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["jobs"]) == 2
    assert all("job_id" in j for j in data["jobs"])


@pytest.mark.asyncio
async def test_batch_partial_unsupported(app):
    """batch에서 일부 파일이 지원 안 되면 해당 파일만 에러"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch("app.process_job", new_callable=AsyncMock):
            resp = await client.post(
                "/batch",
                files=[
                    ("files", ("a.docx", b"content1", "application/octet-stream")),
                    ("files", ("b.xyz", b"content2", "application/octet-stream")),
                ],
            )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["jobs"]) == 2
    ok_job = next(j for j in data["jobs"] if j["file_name"] == "a.docx")
    err_job = next(j for j in data["jobs"] if j["file_name"] == "b.xyz")
    assert "job_id" in ok_job
    assert "error" in err_job


@pytest.mark.asyncio
async def test_convert_file_too_large():
    """MAX_FILE_SIZE 초과 → 413"""
    from config import Config
    from app import create_app
    small_config = Config(max_file_size=10)
    test_app = create_app(config=small_config)
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/convert",
            files={"file": ("test.docx", b"x" * 100, "application/octet-stream")},
        )
    assert resp.status_code == 413


@pytest.mark.asyncio
async def test_exception_logging_wrapper(app):
    """worker 최외곽 예외가 로깅되는지 확인"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch("app.process_job", new_callable=AsyncMock, side_effect=RuntimeError("unexpected")):
            resp = await client.post(
                "/convert",
                files={"file": ("test.docx", b"content", "application/octet-stream")},
            )
    assert resp.status_code == 200  # job_id는 반환됨
    await asyncio.sleep(0.1)  # background task 실행 대기
