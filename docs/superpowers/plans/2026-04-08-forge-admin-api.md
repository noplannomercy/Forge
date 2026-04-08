# Forge 관리 API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cortex 백오피스 + 운영자가 Job 목록 조회, 통계, 메타 수정, 재처리, 삭제를 할 수 있는 관리 API 8개 엔드포인트 구현.

**Architecture:** `admin.py` (FastAPI APIRouter)로 관리 엔드포인트 분리. `auth.py`로 API 키 인증 (FastAPI Depends). `job_store.py`에 목록/통계/삭제 쿼리 메서드 추가. 기존 `app.py`에 라우터 마운트.

**Tech Stack:** Python 3.11, FastAPI, asyncpg, PostgreSQL, pytest, pytest-asyncio

---

## File Map

| 파일 | 역할 | Task |
|------|------|------|
| `config.py` | `forge_api_key` 추가 | 1 |
| `schema.sql` | `deleted_at` 컬럼 추가 | 1 |
| `.env.example` | `FORGE_API_KEY` 추가 | 1 |
| `auth.py` | 신규 — API 키 인증 dependency | 2 |
| `job_store.py` | list_jobs, get_full, update_meta, soft_delete, stats 메서드 추가 | 3 |
| `admin.py` | 신규 — 관리 API 라우터 8개 엔드포인트 | 4 |
| `app.py` | admin 라우터 마운트 | 5 |
| `tests/test_auth.py` | 신규 — 인증 테스트 | 2 |
| `tests/test_admin.py` | 신규 — 관리 API 테스트 | 4-5 |

---

### Task 1: Config + Schema 확장

**Files:**
- Modify: `config.py`
- Modify: `schema.sql`
- Modify: `.env.example`
- Modify: `tests/test_config.py`

- [ ] **Step 1: 테스트 작성**

```python
# tests/test_config.py 에 추가
def test_config_forge_api_key_default():
    config = Config()
    assert config.forge_api_key == ""


def test_config_forge_api_key_from_env(monkeypatch):
    monkeypatch.setenv("FORGE_API_KEY", "my-secret-key")
    config = Config()
    assert config.forge_api_key == "my-secret-key"
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/test_config.py -v -k "forge_api_key"`
Expected: FAIL

- [ ] **Step 3: config.py 구현**

`config.py`의 `meta_llm_api_key` 뒤에 추가:

```python
    # 관리 API 인증
    forge_api_key: str = ""
```

- [ ] **Step 4: schema.sql에 deleted_at 추가**

`forge_jobs` 테이블 정의에서 `error TEXT` 뒤에 추가:

```sql
    deleted_at      TIMESTAMPTZ
```

별도 마이그레이션 SQL도 추가 (기존 테이블용):

```sql
-- 마이그레이션: 기존 테이블에 deleted_at 추가
ALTER TABLE forge_jobs ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;
```

- [ ] **Step 5: .env.example에 추가**

```
FORGE_API_KEY=
```

- [ ] **Step 6: 테스트 통과 확인**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/test_config.py -v`
Expected: 통과

- [ ] **Step 7: 커밋**

```bash
git add config.py schema.sql .env.example tests/test_config.py
git commit -m "feat: forge_api_key config + deleted_at column"
```

---

### Task 2: 인증 모듈

**Files:**
- Create: `auth.py`
- Create: `tests/test_auth.py`

- [ ] **Step 1: 테스트 작성**

```python
# tests/test_auth.py
import pytest
from unittest.mock import MagicMock
from fastapi import HTTPException
from auth import verify_api_key


def test_verify_api_key_valid():
    """유효한 키 → 통과"""
    config = MagicMock()
    config.forge_api_key = "secret-123"
    dep = verify_api_key(config)
    # 예외 안 던지면 OK
    result = dep("secret-123")
    assert result is None


def test_verify_api_key_invalid():
    """잘못된 키 → 401"""
    config = MagicMock()
    config.forge_api_key = "secret-123"
    dep = verify_api_key(config)
    with pytest.raises(HTTPException) as exc_info:
        dep("wrong-key")
    assert exc_info.value.status_code == 401


def test_verify_api_key_missing():
    """키 없음 → 401"""
    config = MagicMock()
    config.forge_api_key = "secret-123"
    dep = verify_api_key(config)
    with pytest.raises(HTTPException) as exc_info:
        dep(None)
    assert exc_info.value.status_code == 401


def test_verify_api_key_disabled():
    """FORGE_API_KEY 빈 값 → 인증 비활성화, 어떤 키든 통과"""
    config = MagicMock()
    config.forge_api_key = ""
    dep = verify_api_key(config)
    result = dep(None)
    assert result is None
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/test_auth.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: auth.py 구현**

```python
# auth.py
from fastapi import Header, HTTPException

from config import Config


def verify_api_key(config: Config):
    """API 키 인증 dependency 팩토리. config.forge_api_key가 빈 값이면 인증 비활성화."""
    def _verify(x_forge_key: str | None = Header(None)):
        if not config.forge_api_key:
            return None  # 인증 비활성화
        if x_forge_key != config.forge_api_key:
            raise HTTPException(status_code=401, detail="Invalid or missing API key")
        return None
    return _verify
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/test_auth.py -v`
Expected: 4 passed

- [ ] **Step 5: 커밋**

```bash
git add auth.py tests/test_auth.py
git commit -m "feat: API key auth dependency for admin endpoints"
```

---

### Task 3: JobStore 관리 메서드 추가

**Files:**
- Modify: `job_store.py`
- Create: `tests/test_admin_store.py`

- [ ] **Step 1: 테스트 작성**

```python
# tests/test_admin_store.py
import pytest
from unittest.mock import AsyncMock, MagicMock
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
    mock_pool.fetchval.assert_called_once()
    mock_pool.fetch.assert_called_once()


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
    mock_pool.execute.assert_called_once()


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
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/test_admin_store.py -v`
Expected: FAIL — `AttributeError: 'PostgresJobStore' object has no attribute 'list_jobs'`

- [ ] **Step 3: job_store.py에 관리 메서드 추가**

`PostgresJobStore` 클래스에 추가:

```python
    async def list_jobs(
        self, page: int = 1, size: int = 20,
        status: str | None = None, source_format: str | None = None,
        requested_by: str | None = None,
    ) -> tuple[list[dict], int]:
        """Job 목록 조회 (필터+페이징). deleted_at IS NULL만."""
        conditions = ["deleted_at IS NULL"]
        params = []
        idx = 1

        if status:
            conditions.append(f"status = ${idx}")
            params.append(status)
            idx += 1
        if source_format:
            conditions.append(f"source_format = ${idx}")
            params.append(source_format)
            idx += 1
        if requested_by:
            conditions.append(f"requested_by = ${idx}")
            params.append(requested_by)
            idx += 1

        where = " AND ".join(conditions)

        total = await self._pool.fetchval(
            f"SELECT COUNT(*) FROM forge_jobs WHERE {where}", *params
        )

        offset = (page - 1) * size
        rows = await self._pool.fetch(
            f"""SELECT id, file_name, status, route, method, source_format,
                       requested_by, meta, processing_ms, created_at, deleted_at
                FROM forge_jobs WHERE {where}
                ORDER BY created_at DESC
                LIMIT ${idx} OFFSET ${idx + 1}""",
            *params, size, offset,
        )

        jobs = []
        for row in rows:
            meta = row["meta"]
            if isinstance(meta, str):
                meta = json.loads(meta)
            jobs.append({
                "id": str(row["id"]),
                "file_name": row["file_name"],
                "status": row["status"],
                "route": row["route"],
                "method": row["method"],
                "source_format": row["source_format"],
                "requested_by": row["requested_by"],
                "meta": meta or {},
                "processing_ms": row["processing_ms"],
                "created_at": str(row["created_at"]),
            })

        return jobs, total

    async def soft_delete(self, job_id: str) -> bool:
        """Soft delete. 반환: 삭제 성공 여부."""
        result = await self._pool.execute(
            "UPDATE forge_jobs SET deleted_at = NOW() WHERE id = $1 AND deleted_at IS NULL",
            job_id,
        )
        return result == "UPDATE 1"

    async def update_meta(self, job_id: str, meta_patch: dict) -> dict:
        """메타 merge. 기존 meta에 patch를 병합. 병합된 결과 반환."""
        existing = await self._pool.fetchval(
            "SELECT meta FROM forge_jobs WHERE id = $1", job_id
        )
        if existing is None:
            return {}
        current = json.loads(existing) if isinstance(existing, str) else (existing or {})
        current.update(meta_patch)
        await self._pool.execute(
            "UPDATE forge_jobs SET meta = $1 WHERE id = $2",
            json.dumps(current), job_id,
        )
        return current

    async def stats_daily(self, from_date: str, to_date: str) -> list[dict]:
        rows = await self._pool.fetch(
            """SELECT DATE(created_at) AS day,
                      COUNT(*) AS total,
                      COUNT(*) FILTER (WHERE status = 'completed') AS success,
                      COUNT(*) FILTER (WHERE status = 'failed') AS failed,
                      AVG(processing_ms) AS avg_ms
               FROM forge_jobs
               WHERE created_at >= $1::date AND created_at < $2::date + 1
                     AND deleted_at IS NULL
               GROUP BY DATE(created_at)
               ORDER BY day""",
            from_date, to_date,
        )
        return [dict(r) for r in rows]

    async def stats_cost(self, from_date: str, to_date: str) -> list[dict]:
        rows = await self._pool.fetch(
            """SELECT DATE(l.created_at) AS day,
                      COALESCE(SUM(l.cost_usd), 0) AS total_cost_usd,
                      COALESCE(SUM(l.input_tokens + l.output_tokens), 0) AS total_tokens
               FROM forge_vlm_logs l
               JOIN forge_jobs j ON l.job_id = j.id
               WHERE l.created_at >= $1::date AND l.created_at < $2::date + 1
                     AND j.deleted_at IS NULL
               GROUP BY DATE(l.created_at)
               ORDER BY day""",
            from_date, to_date,
        )
        return [dict(r) for r in rows]

    async def stats_models(self) -> list[dict]:
        rows = await self._pool.fetch(
            """SELECT model,
                      COUNT(*) AS calls,
                      AVG(latency_ms) AS avg_latency_ms,
                      COALESCE(SUM(cost_usd), 0) AS total_cost_usd,
                      COALESCE(SUM(input_tokens), 0) AS total_input_tokens,
                      COALESCE(SUM(output_tokens), 0) AS total_output_tokens
               FROM forge_vlm_logs
               GROUP BY model
               ORDER BY calls DESC"""
        )
        return [dict(r) for r in rows]
```

`get` 메서드도 수정 — soft delete된 Job 조회 차단:

현재 `get`의 SQL을 변경:
```python
    async def get(self, job_id: str) -> Job | None:
        row = await self._pool.fetchrow(
            "SELECT * FROM forge_jobs WHERE id = $1 AND deleted_at IS NULL", job_id
        )
        if row is None:
            return None
        return self._row_to_job(row)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/test_admin_store.py tests/test_postgres_store.py -v`
Expected: 통과

- [ ] **Step 5: 커밋**

```bash
git add job_store.py tests/test_admin_store.py
git commit -m "feat: JobStore admin methods — list, soft delete, meta merge, stats"
```

---

### Task 4: Admin 라우터

**Files:**
- Create: `admin.py`
- Create: `tests/test_admin.py`

- [ ] **Step 1: 테스트 작성**

```python
# tests/test_admin.py
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
        resp = await client.get("/jobs")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_admin_valid_auth(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/jobs", headers={"X-Forge-Key": "test-key"})
    # InMemoryJobStore는 list_jobs가 없으므로 500 또는 구현에 따라 다름
    # 최소한 401이 아닌지 확인
    assert resp.status_code != 401


@pytest.mark.asyncio
async def test_admin_no_auth_when_disabled(app_no_auth):
    transport = ASGITransport(app=app_no_auth)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/jobs")
    assert resp.status_code != 401


@pytest.mark.asyncio
async def test_delete_job(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 먼저 job 생성
        with patch("app.process_job", new_callable=AsyncMock):
            create_resp = await client.post(
                "/convert",
                files={"file": ("test.docx", b"content", "application/octet-stream")},
            )
        job_id = create_resp.json()["job_id"]

        # InMemoryJobStore soft_delete 호출
        resp = await client.delete(
            f"/jobs/{job_id}",
            headers={"X-Forge-Key": "test-key"},
        )
    assert resp.status_code == 200
    assert resp.json()["deleted"] is True


@pytest.mark.asyncio
async def test_delete_nonexistent(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.delete(
            "/jobs/nonexistent-id",
            headers={"X-Forge-Key": "test-key"},
        )
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
async def test_retry_meta(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch("app.process_job", new_callable=AsyncMock):
            create_resp = await client.post(
                "/convert",
                files={"file": ("test.docx", b"content", "application/octet-stream")},
            )
        job_id = create_resp.json()["job_id"]

        # result가 없는 상태에서 retry → 400
        resp = await client.post(
            f"/jobs/{job_id}/retry",
            headers={"X-Forge-Key": "test-key"},
        )
    assert resp.status_code == 400
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/test_admin.py -v`
Expected: FAIL

- [ ] **Step 3: admin.py 구현**

```python
# admin.py
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel


class MetaPatch(BaseModel):
    """메타 수정 요청 바디. 자유 형식 dict."""
    class Config:
        extra = "allow"


def create_admin_router(app_state, auth_dep) -> APIRouter:
    router = APIRouter(dependencies=[Depends(auth_dep)])

    @router.get("/jobs")
    async def list_jobs(
        status: str | None = Query(None),
        source_format: str | None = Query(None),
        requested_by: str | None = Query(None),
        page: int = Query(1, ge=1),
        size: int = Query(20, ge=1, le=100),
    ):
        store = app_state.store
        if not hasattr(store, "list_jobs"):
            raise HTTPException(status_code=501, detail="list_jobs not supported (InMemoryJobStore)")
        jobs, total = await store.list_jobs(
            page=page, size=size,
            status=status, source_format=source_format, requested_by=requested_by,
        )
        return {"jobs": jobs, "total": total, "page": page, "size": size}

    @router.get("/jobs/{job_id}")
    async def get_job(job_id: str):
        store = app_state.store
        job = await store.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return {
            "id": job.id,
            "file_name": job.file_name,
            "file_size": job.file_size,
            "status": job.status,
            "route": job.route,
            "method": job.method,
            "source_format": job.source_format,
            "requested_by": job.requested_by,
            "result_text": job.result.text if job.result else None,
            "meta": job.meta,
            "quality": job.result.quality.model_dump() if job.result else None,
            "prompt_version": job.prompt_version,
            "meta_prompt_version": job.meta_prompt_version,
            "processing_ms": job.processing_ms,
            "created_at": str(job.created_at),
            "started_at": str(job.started_at) if job.started_at else None,
            "completed_at": str(job.completed_at) if job.completed_at else None,
            "error": job.error,
        }

    @router.patch("/jobs/{job_id}/meta")
    async def patch_meta(job_id: str, body: dict):
        store = app_state.store
        job = await store.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")

        if hasattr(store, "update_meta"):
            merged = await store.update_meta(job_id, body)
        else:
            # InMemoryJobStore fallback
            job.meta.update(body)
            merged = job.meta

        return {"meta": merged}

    @router.post("/jobs/{job_id}/retry")
    async def retry_meta(job_id: str):
        store = app_state.store
        job = await store.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        if not job.result:
            raise HTTPException(status_code=400, detail="Job has no result yet")

        meta_extractor = getattr(app_state, "meta_extractor", None)
        if meta_extractor is None:
            raise HTTPException(status_code=503, detail="MetaExtractor not available")

        meta = await meta_extractor.extract(job.result.text)
        await store.save_meta(job_id, meta)
        return {"meta": meta}

    @router.delete("/jobs/{job_id}")
    async def delete_job(job_id: str):
        store = app_state.store
        if hasattr(store, "soft_delete"):
            deleted = await store.soft_delete(job_id)
        else:
            # InMemoryJobStore fallback
            job = await store.get(job_id)
            if job is None:
                deleted = False
            else:
                store._jobs.pop(job_id, None)
                deleted = True

        if not deleted:
            raise HTTPException(status_code=404, detail="Job not found")
        return {"deleted": True}

    @router.get("/stats/daily")
    async def stats_daily(
        from_date: str | None = Query(None, alias="from"),
        to_date: str | None = Query(None, alias="to"),
    ):
        store = app_state.store
        if not hasattr(store, "stats_daily"):
            raise HTTPException(status_code=501, detail="stats not supported (InMemoryJobStore)")
        f = from_date or str(date.today() - timedelta(days=7))
        t = to_date or str(date.today())
        stats = await store.stats_daily(f, t)
        return {"stats": stats}

    @router.get("/stats/cost")
    async def stats_cost(
        from_date: str | None = Query(None, alias="from"),
        to_date: str | None = Query(None, alias="to"),
    ):
        store = app_state.store
        if not hasattr(store, "stats_cost"):
            raise HTTPException(status_code=501, detail="stats not supported (InMemoryJobStore)")
        f = from_date or str(date.today() - timedelta(days=7))
        t = to_date or str(date.today())
        stats = await store.stats_cost(f, t)
        return {"stats": stats}

    @router.get("/stats/models")
    async def stats_models():
        store = app_state.store
        if not hasattr(store, "stats_models"):
            raise HTTPException(status_code=501, detail="stats not supported (InMemoryJobStore)")
        stats = await store.stats_models()
        return {"models": stats}

    return router
```

- [ ] **Step 4: 테스트 통과 확인은 Task 5에서 app.py 마운트 후.**

- [ ] **Step 5: 커밋**

```bash
git add admin.py tests/test_admin.py
git commit -m "feat: admin router — 8 management API endpoints"
```

---

### Task 5: App에 Admin 라우터 마운트 + 전체 테스트

**Files:**
- Modify: `app.py`

- [ ] **Step 1: app.py 수정 — admin 라우터 마운트**

`create_app` 함수 내, lifespan 정의 후, 엔드포인트 정의 전에:

```python
    from auth import verify_api_key
    from admin import create_admin_router

    auth_dep = verify_api_key(config)
    admin_router = create_admin_router(app.state, auth_dep)
    app.include_router(admin_router)
```

주의: `app.state`를 넘기므로 라우터 마운트는 `app = FastAPI(...)` ��후에 해야 함.

전체 `create_app`에서 `app = FastAPI(...)` 직후, `@app.get("/health")` 전에 위 코드 추가.

- [ ] **Step 2: 전체 테스트 실행**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/ -v`
Expected: 전체 통과 (기존 test_config_defaults 1개 제외)

- [ ] **Step 3: InMemoryJobStore에 soft_delete 추가** (테스트에서 필요)

```python
# job_store.py InMemoryJobStore에 추가
async def soft_delete(self, job_id: str) -> bool:
    if job_id in self._jobs:
        del self._jobs[job_id]
        return True
    return False
```

- [ ] **Step 4: 전체 테스트 재실행**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/ -v`
Expected: 전체 통과

- [ ] **Step 5: 커밋**

```bash
git add app.py job_store.py
git commit -m "feat: mount admin router + InMemoryJobStore soft_delete"
```

---
