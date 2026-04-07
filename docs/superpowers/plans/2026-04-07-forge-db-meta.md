# Forge DB + LLM 메타 추출 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** InMemoryJobStore를 PostgreSQL로 교체하고, 변환 완료 후 LLM으로 문서 메타데이터를 자동 추출하여 JSONB에 저장한다.

**Architecture:** Cortex PostgreSQL에 forge_ 테이블 생성. JobStore ABC 구현체를 PostgresJobStore로 교체. 변환 워커에 메타 추출 단계 추가. VLM 호출마다 forge_vlm_logs에 비용/토큰 기록.

**Tech Stack:** Python 3.11, FastAPI, asyncpg, PostgreSQL, httpx, pytest, pytest-asyncio

---

## File Map

| 파일 | 역할 | Task |
|------|------|------|
| `schema.sql` | DDL 스크립트 (테이블, 인덱스, materialized view) | 1 |
| `requirements.txt` | asyncpg 추가 | 1 |
| `config.py` | DATABASE_URL, META_LLM_* 추가 | 1 |
| `.env.example` | 환경변수 템플릿 업데이트 | 1 |
| `models.py` | Job에 requested_by, meta, prompt_version 등 추가 | 2 |
| `job_store.py` | PostgresJobStore + VLMLogStore 구현 | 3 |
| `meta.py` | 신규 — 메타 추출 LLM 클라이언트 | 4 |
| `vlm.py` | BatchResult에 토큰/비용 정보 추가 | 5 |
| `worker.py` | 메타 추출 단계 + vlm_logs 기록 | 6 |
| `app.py` | requested_by, ?format=text, DB 연결 lifecycle | 7 |
| `tests/` | 각 Task별 테스트 | 1-7 |

---

### Task 1: 스키마 + Config + 의존성

**Files:**
- Create: `schema.sql`
- Modify: `config.py`
- Modify: `requirements.txt`
- Modify: `.env.example`
- Modify: `tests/test_config.py`

- [ ] **Step 1: 테스트 작성 — config.py 확장**

```python
# tests/test_config.py 에 추가
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
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/test_config.py -v -k "database or meta_llm"`
Expected: FAIL — `unexpected keyword argument`

- [ ] **Step 3: config.py 구현**

```python
# config.py
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    vlm_url: str = "http://localhost:11434/v1/chat/completions"
    vlm_model: str = "qwen2-vl:7b"
    vlm_api_key: str = ""
    vlm_timeout: int = 120
    vlm_concurrency: int = 3
    vlm_batch_size: int = 5
    host: str = "0.0.0.0"
    port: int = 8003
    max_file_size: int = 104_857_600  # 100MB

    # DB
    database_url: str = ""

    # 메타 추출 LLM (미설정 시 VLM 설정 fallback)
    meta_llm_url: str = ""
    meta_llm_model: str = ""
    meta_llm_api_key: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/test_config.py -v`
Expected: 통과

- [ ] **Step 5: schema.sql 작성**

```sql
-- schema.sql
-- Forge DB schema (Cortex PostgreSQL, forge_ 접두사)

CREATE TABLE IF NOT EXISTS forge_jobs (
    id              UUID PRIMARY KEY,
    file_name       VARCHAR(500) NOT NULL,
    file_size       BIGINT,
    source_format   VARCHAR(20) NOT NULL,
    route           VARCHAR(20) NOT NULL,
    method          VARCHAR(20) NOT NULL DEFAULT 'extract',
    status          VARCHAR(20) NOT NULL DEFAULT 'queued',
    requested_by    VARCHAR(100),
    result_text     TEXT,
    meta            JSONB DEFAULT '{}',
    quality         JSONB DEFAULT '{}',
    prompt_version      VARCHAR(50),
    meta_prompt_version VARCHAR(50),
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    processing_ms   INT,
    error           TEXT
);

CREATE TABLE IF NOT EXISTS forge_vlm_logs (
    id              SERIAL PRIMARY KEY,
    job_id          UUID REFERENCES forge_jobs(id),
    batch_num       INT,
    purpose         VARCHAR(20),
    model           VARCHAR(100),
    prompt_version  VARCHAR(50),
    input_tokens    INT,
    output_tokens   INT,
    cost_usd        DECIMAL(10,6),
    latency_ms      INT,
    success         BOOLEAN,
    error           TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_forge_jobs_status ON forge_jobs(status);
CREATE INDEX IF NOT EXISTS idx_forge_jobs_meta ON forge_jobs USING GIN(meta);
CREATE INDEX IF NOT EXISTS idx_forge_jobs_created ON forge_jobs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_forge_jobs_requested_by ON forge_jobs(requested_by);
CREATE INDEX IF NOT EXISTS idx_forge_vlm_logs_job ON forge_vlm_logs(job_id);
CREATE INDEX IF NOT EXISTS idx_forge_vlm_logs_model ON forge_vlm_logs(model);
```

- [ ] **Step 6: requirements.txt에 asyncpg 추가**

`requirements.txt`에 추가:
```
asyncpg>=0.29.0
```

- [ ] **Step 7: .env.example 업데이트**

`.env.example`에 추가:
```
DATABASE_URL=postgresql://user:pass@localhost:5432/cortex
META_LLM_URL=
META_LLM_MODEL=
META_LLM_API_KEY=
```

- [ ] **Step 8: pip install asyncpg**

Run: `cd C:/workspace/prj20060203/Forge && pip install asyncpg`

- [ ] **Step 9: 커밋**

```bash
git add schema.sql config.py requirements.txt .env.example tests/test_config.py
git commit -m "feat: schema.sql + config for DB and meta LLM"
```

---

### Task 2: Models 확장

**Files:**
- Modify: `models.py`
- Modify: `tests/test_models.py`

- [ ] **Step 1: 테스트 작성 — Job 확장**

```python
# tests/test_models.py 에 추가
def test_job_with_extended_fields():
    job = Job(
        id="test-uuid",
        status=JobStatus.QUEUED,
        file_name="test.pdf",
        source_format="pdf",
        route="vlm",
        method="semantic",
        requested_by="cortex-api",
        file_size=1024000,
        prompt_version="semantic-v1",
    )
    assert job.method == "semantic"
    assert job.requested_by == "cortex-api"
    assert job.file_size == 1024000
    assert job.prompt_version == "semantic-v1"
    assert job.meta == {}
    assert job.meta_prompt_version is None
    assert job.started_at is None
    assert job.processing_ms is None


def test_job_with_meta():
    job = Job(
        id="test-uuid",
        status=JobStatus.COMPLETED,
        file_name="제안서.pdf",
        source_format="pdf",
        route="vlm",
        meta={"category": "제안서", "client": "안산시"},
    )
    assert job.meta["category"] == "제안서"
    assert job.meta["client"] == "안산시"
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/test_models.py -v -k "extended or meta"`
Expected: FAIL

- [ ] **Step 3: models.py 구현 — Job 확장**

```python
class Job(BaseModel):
    id: str
    status: JobStatus
    file_name: str
    file_size: int | None = None
    source_format: str
    route: str
    method: str = "extract"
    requested_by: str | None = None
    result: ConvertResult | None = None
    meta: dict = Field(default_factory=dict)
    prompt_version: str | None = None
    meta_prompt_version: str | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: datetime | None = None
    completed_at: datetime | None = None
    processing_ms: int | None = None
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/test_models.py -v`
Expected: 통과

- [ ] **Step 5: 커밋**

```bash
git add models.py tests/test_models.py
git commit -m "feat: Job model with meta, requested_by, prompt_version, timing"
```

---

### Task 3: PostgresJobStore + VLMLogStore

**Files:**
- Modify: `job_store.py`
- Create: `tests/test_postgres_store.py`

- [ ] **Step 1: 테스트 작성 — PostgresJobStore (mock asyncpg)**

```python
# tests/test_postgres_store.py
import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from job_store import PostgresJobStore, VLMLogStore
from models import JobStatus, ConvertResult, Quality


@pytest.fixture
def mock_pool():
    pool = AsyncMock()
    return pool


@pytest.fixture
def store(mock_pool):
    return PostgresJobStore(mock_pool)


@pytest.fixture
def vlm_log_store(mock_pool):
    return VLMLogStore(mock_pool)


@pytest.mark.asyncio
async def test_create_job(store, mock_pool):
    mock_pool.fetchrow = AsyncMock(return_value={
        "id": "test-uuid", "status": "queued", "file_name": "test.pdf",
        "file_size": 1024, "source_format": "pdf", "route": "vlm",
        "method": "semantic", "requested_by": None, "result_text": None,
        "meta": "{}", "quality": "{}", "prompt_version": None,
        "meta_prompt_version": None, "error": None,
        "created_at": "2026-04-07T00:00:00+00:00", "started_at": None,
        "completed_at": None, "processing_ms": None,
    })

    job = await store.create("test.pdf", "pdf", "vlm", file_size=1024, method="semantic")
    assert job.file_name == "test.pdf"
    assert job.route == "vlm"
    mock_pool.fetchrow.assert_called_once()


@pytest.mark.asyncio
async def test_get_job(store, mock_pool):
    mock_pool.fetchrow = AsyncMock(return_value={
        "id": "test-uuid", "status": "queued", "file_name": "test.pdf",
        "file_size": None, "source_format": "pdf", "route": "vlm",
        "method": "extract", "requested_by": None, "result_text": None,
        "meta": "{}", "quality": "{}", "prompt_version": None,
        "meta_prompt_version": None, "error": None,
        "created_at": "2026-04-07T00:00:00+00:00", "started_at": None,
        "completed_at": None, "processing_ms": None,
    })

    job = await store.get("test-uuid")
    assert job is not None
    assert job.id == "test-uuid"


@pytest.mark.asyncio
async def test_get_nonexistent(store, mock_pool):
    mock_pool.fetchrow = AsyncMock(return_value=None)
    job = await store.get("nonexistent")
    assert job is None


@pytest.mark.asyncio
async def test_update_status(store, mock_pool):
    mock_pool.execute = AsyncMock()
    await store.update_status("test-uuid", JobStatus.PROCESSING)
    mock_pool.execute.assert_called_once()


@pytest.mark.asyncio
async def test_save_result(store, mock_pool):
    mock_pool.execute = AsyncMock()
    quality = Quality(total_chars=100, chars_per_page=100, total_pages=1, failed_pages=0, confidence="high", method="semantic")
    result = ConvertResult(
        text="# Hello", format="md", pages=1,
        file_name="test.pdf", source_format="pdf",
        route="vlm", quality=quality,
    )
    await store.save_result("test-uuid", result)
    mock_pool.execute.assert_called_once()


@pytest.mark.asyncio
async def test_save_meta(store, mock_pool):
    mock_pool.execute = AsyncMock()
    await store.save_meta("test-uuid", {"category": "제안서"}, "meta-v1")
    mock_pool.execute.assert_called_once()


@pytest.mark.asyncio
async def test_save_error(store, mock_pool):
    mock_pool.execute = AsyncMock()
    await store.save_error("test-uuid", "conversion failed")
    mock_pool.execute.assert_called_once()


@pytest.mark.asyncio
async def test_vlm_log_insert(vlm_log_store, mock_pool):
    mock_pool.execute = AsyncMock()
    await vlm_log_store.log(
        job_id="test-uuid", batch_num=1, purpose="convert",
        model="gemini-2.0-flash", prompt_version="semantic-v1",
        input_tokens=1000, output_tokens=500, cost_usd=0.0001,
        latency_ms=2500, success=True, error=None,
    )
    mock_pool.execute.assert_called_once()
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/test_postgres_store.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: job_store.py 구현 — PostgresJobStore + VLMLogStore 추가**

기존 `JobStore` ABC와 `InMemoryJobStore`는 유지. 아래를 추가:

```python
# job_store.py 에 추가 (기존 코드 유지)
import json
from typing import Any

import asyncpg


class PostgresJobStore(JobStore):
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    def _row_to_job(self, row: dict) -> Job:
        return Job(
            id=str(row["id"]),
            status=JobStatus(row["status"]),
            file_name=row["file_name"],
            file_size=row["file_size"],
            source_format=row["source_format"],
            route=row["route"],
            method=row.get("method", "extract"),
            requested_by=row["requested_by"],
            meta=json.loads(row["meta"]) if isinstance(row["meta"], str) else (row["meta"] or {}),
            quality=json.loads(row["quality"]) if isinstance(row["quality"], str) else (row["quality"] or {}),
            prompt_version=row["prompt_version"],
            meta_prompt_version=row["meta_prompt_version"],
            error=row["error"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            processing_ms=row["processing_ms"],
        )

    async def create(
        self, file_name: str, source_format: str, route: str,
        file_size: int | None = None, method: str = "extract",
        requested_by: str | None = None,
    ) -> Job:
        job_id = str(uuid.uuid4())
        row = await self._pool.fetchrow(
            """INSERT INTO forge_jobs (id, file_name, file_size, source_format, route, method, status, requested_by)
               VALUES ($1, $2, $3, $4, $5, $6, 'queued', $7)
               RETURNING *""",
            job_id, file_name, file_size, source_format, route, method, requested_by,
        )
        return self._row_to_job(row)

    async def get(self, job_id: str) -> Job | None:
        row = await self._pool.fetchrow("SELECT * FROM forge_jobs WHERE id = $1", job_id)
        if row is None:
            return None
        return self._row_to_job(row)

    async def update_status(self, job_id: str, status: JobStatus) -> None:
        if status == JobStatus.PROCESSING:
            await self._pool.execute(
                "UPDATE forge_jobs SET status = $1, started_at = NOW() WHERE id = $2",
                status.value, job_id,
            )
        else:
            await self._pool.execute(
                "UPDATE forge_jobs SET status = $1 WHERE id = $2",
                status.value, job_id,
            )

    async def save_result(self, job_id: str, result: ConvertResult) -> None:
        await self._pool.execute(
            """UPDATE forge_jobs
               SET status = 'completed', result_text = $1, quality = $2,
                   completed_at = NOW(), processing_ms = EXTRACT(EPOCH FROM (NOW() - COALESCE(started_at, created_at))) * 1000
               WHERE id = $3""",
            result.text, json.dumps(result.quality.model_dump()), job_id,
        )

    async def save_meta(self, job_id: str, meta: dict, meta_prompt_version: str | None = None) -> None:
        await self._pool.execute(
            "UPDATE forge_jobs SET meta = $1, meta_prompt_version = $2 WHERE id = $3",
            json.dumps(meta), meta_prompt_version, job_id,
        )

    async def save_error(self, job_id: str, error: str) -> None:
        await self._pool.execute(
            """UPDATE forge_jobs
               SET status = 'failed', error = $1,
                   completed_at = NOW(), processing_ms = EXTRACT(EPOCH FROM (NOW() - COALESCE(started_at, created_at))) * 1000
               WHERE id = $2""",
            error, job_id,
        )


class VLMLogStore:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def log(
        self, job_id: str, batch_num: int, purpose: str,
        model: str, prompt_version: str | None,
        input_tokens: int | None, output_tokens: int | None,
        cost_usd: float | None, latency_ms: int | None,
        success: bool, error: str | None,
    ) -> None:
        await self._pool.execute(
            """INSERT INTO forge_vlm_logs
               (job_id, batch_num, purpose, model, prompt_version,
                input_tokens, output_tokens, cost_usd, latency_ms, success, error)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)""",
            job_id, batch_num, purpose, model, prompt_version,
            input_tokens, output_tokens, cost_usd, latency_ms, success, error,
        )
```

JobStore ABC의 `create` 시그니처도 확장 필요. 기존 호출 호환성을 위해 기본값 추가:

```python
class JobStore(ABC):
    @abstractmethod
    async def create(self, file_name: str, source_format: str, route: str, **kwargs) -> Job: ...

    @abstractmethod
    async def get(self, job_id: str) -> Job | None: ...

    @abstractmethod
    async def update_status(self, job_id: str, status: JobStatus) -> None: ...

    @abstractmethod
    async def save_result(self, job_id: str, result: ConvertResult) -> None: ...

    @abstractmethod
    async def save_error(self, job_id: str, error: str) -> None: ...
```

InMemoryJobStore의 `create`도 `**kwargs` 추가, `save_meta` 추가:

```python
async def create(self, file_name: str, source_format: str, route: str, **kwargs) -> Job:
    job = Job(
        id=str(uuid.uuid4()),
        status=JobStatus.QUEUED,
        file_name=file_name,
        source_format=source_format,
        route=route,
        **kwargs,
    )
    self._jobs[job.id] = job
    return job

async def save_meta(self, job_id: str, meta: dict, meta_prompt_version: str | None = None) -> None:
    if job_id in self._jobs:
        self._jobs[job_id].meta = meta
        self._jobs[job_id].meta_prompt_version = meta_prompt_version
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/test_postgres_store.py tests/test_job_store.py -v`
Expected: 통과

- [ ] **Step 5: 커밋**

```bash
git add job_store.py tests/test_postgres_store.py
git commit -m "feat: PostgresJobStore + VLMLogStore with asyncpg"
```

---

### Task 4: 메타 추출 LLM 클라이언트

**Files:**
- Create: `meta.py`
- Create: `tests/test_meta.py`

- [ ] **Step 1: 테스트 작성 — meta.py**

```python
# tests/test_meta.py
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

    # 프롬프트에 전달된 텍스트가 3000자로 잘렸는지 확인
    call_args = mock_post.call_args
    payload = call_args[1]["json"] if "json" in call_args[1] else call_args[0][1]
    message_content = payload["messages"][0]["content"]
    # 전체 프롬프트가 원본 10000자보다 짧아야 함
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
    """META_LLM 미설정 시 VLM 설정으로 fallback"""
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
    """META_LLM 설정 시 전용 설정 사용"""
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
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/test_meta.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: meta.py 구현**

```python
# meta.py
import json

import httpx

from config import Config

META_PROMPT = """이 문서를 분석해서 JSON으로 메타데이터를 추출해.

반드시 포함: category, title, summary(2줄), keywords(5개)
가능하면 포함: client, author, date, budget, project_name

JSON만 반환. 다른 텍스트 없이."""

MAX_INPUT_CHARS = 3000


class MetaExtractor:
    def __init__(self, config: Config):
        # META_LLM 설정이 있으면 사용, 없으면 VLM fallback
        self.url = config.meta_llm_url or config.vlm_url
        self.model = config.meta_llm_model or config.vlm_model
        api_key = config.meta_llm_api_key or config.vlm_api_key
        self.headers = {"Content-Type": "application/json"}
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"
        self.client = httpx.AsyncClient(timeout=60)

    async def extract(self, text: str) -> dict:
        """변환된 텍스트에서 메타데이터 추출. 실패 시 빈 dict 반환."""
        try:
            truncated = text[:MAX_INPUT_CHARS]
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "user", "content": f"{META_PROMPT}\n\n---\n\n{truncated}"}
                ],
                "max_tokens": 1024,
            }

            response = await self.client.post(self.url, json=payload, headers=self.headers)
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]

            # JSON 파싱 (다양한 LLM 응답 형식 대응)
            content = content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1]
                content = content.rsplit("```", 1)[0]
            # 설명 텍스트 + JSON 혼합 대응: 첫 { ~ 마지막 } 추출
            start = content.find("{")
            end = content.rfind("}")
            if start != -1 and end != -1:
                content = content[start:end + 1]

            return json.loads(content.strip())
        except Exception:
            return {}

    async def close(self):
        await self.client.aclose()
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/test_meta.py -v`
Expected: 7 passed

- [ ] **Step 5: 커밋**

```bash
git add meta.py tests/test_meta.py
git commit -m "feat: MetaExtractor — LLM auto meta extraction with VLM fallback"
```

---

### Task 5: VLM BatchResult에 토큰/비용 정보 추가

**Files:**
- Modify: `vlm.py`
- Modify: `tests/test_vlm.py`

- [ ] **Step 1: 테스트 추가**

```python
# tests/test_vlm.py 에 추가
@pytest.mark.asyncio
async def test_process_batch_returns_usage(vlm_client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "text"}}],
        "usage": {"prompt_tokens": 1000, "completion_tokens": 500},
    }
    mock_response.raise_for_status = MagicMock()

    with patch.object(vlm_client.client, "post", new_callable=AsyncMock, return_value=mock_response):
        result = await vlm_client.process_batch([b"img1"], batch_num=1)

    assert result.input_tokens == 1000
    assert result.output_tokens == 500


@pytest.mark.asyncio
async def test_process_batch_no_usage_returns_none(vlm_client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "text"}}],
    }
    mock_response.raise_for_status = MagicMock()

    with patch.object(vlm_client.client, "post", new_callable=AsyncMock, return_value=mock_response):
        result = await vlm_client.process_batch([b"img1"], batch_num=1)

    assert result.input_tokens is None
    assert result.output_tokens is None
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/test_vlm.py -v -k "usage"`
Expected: FAIL — `AttributeError: 'BatchResult' object has no attribute 'input_tokens'`

- [ ] **Step 3: vlm.py 수정 — BatchResult 확장 + usage 파싱**

BatchResult에 토큰 필드 추가:

```python
class BatchResult:
    def __init__(
        self, batch_num: int, text: str, success: bool,
        error: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        latency_ms: int | None = None,
    ):
        self.batch_num = batch_num
        self.text = text
        self.success = success
        self.error = error
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.latency_ms = latency_ms
```

`process_batch`에서 usage 파싱 + latency 측정:

성공 시:
```python
import time

# process_batch 내부, try 블록 시작 부분에 시간 측정 추가
start_time = time.monotonic()
# ... 기존 호출 코드 ...
elapsed_ms = int((time.monotonic() - start_time) * 1000)

usage = data.get("usage", {})
return BatchResult(
    batch_num=batch_num, text=text, success=True,
    input_tokens=usage.get("prompt_tokens"),
    output_tokens=usage.get("completion_tokens"),
    latency_ms=elapsed_ms,
)
```

실패 시:
```python
return BatchResult(
    batch_num=batch_num,
    text=f"[변환 실패: 페이지 {start_page}-{end_page}]",
    success=False, error=str(last_error),
)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/test_vlm.py -v`
Expected: 9 passed

- [ ] **Step 5: 커밋**

```bash
git add vlm.py tests/test_vlm.py
git commit -m "feat: BatchResult with token usage and latency tracking"
```

---

### Task 6: Worker — 메타 추출 + VLM 로그 기록

**Files:**
- Modify: `worker.py`
- Modify: `tests/test_worker.py`

- [ ] **Step 1: 테스트 추가**

```python
# tests/test_worker.py 에 추가
@pytest.mark.asyncio
async def test_worker_vlm_calls_meta_extraction(store, config):
    """VLM 변환 후 메타 추출이 호출되는지 확인"""
    job = await store.create("scan.pdf", "pdf", "vlm")

    mock_doc_result = DocumentResult(
        text="# Scanned", total_pages=1, failed_pages=0,
        confidence="high", total_batches=1, failed_batches=0,
    )

    with patch("worker.pdf_to_images", new_callable=AsyncMock, return_value=[b"img"]):
        with patch("worker.VLMClient") as MockVLM:
            mock_vlm = AsyncMock()
            mock_vlm.process_document = AsyncMock(return_value=mock_doc_result)
            mock_vlm.close = AsyncMock()
            MockVLM.return_value = mock_vlm

            with patch("worker.MetaExtractor") as MockMeta:
                mock_meta = AsyncMock()
                mock_meta.extract = AsyncMock(return_value={"category": "보고서"})
                mock_meta.close = AsyncMock()
                MockMeta.return_value = mock_meta

                await process_job(job, b"fake", "vlm", store, config)

    updated = await store.get(job.id)
    assert updated.status == JobStatus.COMPLETED
    mock_meta.extract.assert_called_once()


@pytest.mark.asyncio
async def test_worker_meta_failure_doesnt_fail_job(store, config):
    """메타 추출 실패해도 job은 completed"""
    job = await store.create("scan.pdf", "pdf", "vlm")

    mock_doc_result = DocumentResult(
        text="# Scanned", total_pages=1, failed_pages=0,
        confidence="high", total_batches=1, failed_batches=0,
    )

    with patch("worker.pdf_to_images", new_callable=AsyncMock, return_value=[b"img"]):
        with patch("worker.VLMClient") as MockVLM:
            mock_vlm = AsyncMock()
            mock_vlm.process_document = AsyncMock(return_value=mock_doc_result)
            mock_vlm.close = AsyncMock()
            MockVLM.return_value = mock_vlm

            with patch("worker.MetaExtractor") as MockMeta:
                mock_meta = AsyncMock()
                mock_meta.extract = AsyncMock(side_effect=Exception("LLM down"))
                mock_meta.close = AsyncMock()
                MockMeta.return_value = mock_meta

                await process_job(job, b"fake", "vlm", store, config)

    updated = await store.get(job.id)
    assert updated.status == JobStatus.COMPLETED


@pytest.mark.asyncio
async def test_worker_extract_calls_meta_extraction(store, config):
    """extract 경로도 메타 추출 호출"""
    job = await store.create("test.docx", "docx", "extract")

    mock_result = ConvertResult(
        text="# Hello",
        format="md",
        pages=1,
        file_name="test.docx",
        source_format="docx",
        route="extract",
        quality=Quality(total_chars=7, chars_per_page=7, total_pages=1,
                       failed_pages=0, confidence="high", method="extract"),
    )

    with patch("worker.EXTRACTORS", {"docx": AsyncMock(return_value=mock_result)}):
        with patch("worker.MetaExtractor") as MockMeta:
            mock_meta = AsyncMock()
            mock_meta.extract = AsyncMock(return_value={"category": "문서"})
            mock_meta.close = AsyncMock()
            MockMeta.return_value = mock_meta

            await process_job(job, b"fake", "extract", store, config)

    mock_meta.extract.assert_called_once()
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/test_worker.py -v -k "meta"`
Expected: FAIL

- [ ] **Step 3: worker.py 수정**

```python
# worker.py
import logging

from config import Config
from extractors import EXTRACTORS
from extractors.image import prepare_image
from extractors.office import pptx_to_pdf
from extractors.pdf import extract_text, pdf_to_images
from job_store import JobStore
from meta import MetaExtractor
from models import ConvertResult, DocumentResult, Job, JobStatus, Quality
from vlm import VLMClient

logger = logging.getLogger(__name__)

PROMPT_VERSION = "semantic-v1"
META_PROMPT_VERSION = "meta-v1"


async def _extract_meta(result_text: str, meta_extractor: MetaExtractor | None, config: Config) -> dict:
    """메타 추출. 실패 시 빈 dict 반환. meta_extractor가 없으면 임시 생성."""
    extractor = meta_extractor
    should_close = False
    if extractor is None:
        extractor = MetaExtractor(config)
        should_close = True
    try:
        return await extractor.extract(result_text)
    except Exception:
        logger.warning("Meta extraction failed for job", exc_info=True)
        return {}
    finally:
        if should_close:
            await extractor.close()


async def process_job(
    job: Job,
    file_bytes: bytes,
    route: str,
    store: JobStore,
    config: Config,
    meta_extractor: MetaExtractor | None = None,
) -> None:
    """비동기 변환 워커. asyncio.create_task로 호출됨."""
    await store.update_status(job.id, JobStatus.PROCESSING)

    try:
        if route == "extract":
            if job.source_format == "pdf":
                result = await extract_text(file_bytes, job.file_name)
            else:
                result = await EXTRACTORS[job.source_format](file_bytes, job.file_name)
            await store.save_result(job.id, result)

            # extract 경로도 메타 추출
            meta = await _extract_meta(result.text, meta_extractor, config)
            if hasattr(store, "save_meta") and meta:
                await store.save_meta(job.id, meta, META_PROMPT_VERSION)

        elif route == "vlm":
            # 이미지 준비
            if job.source_format == "pptx":
                pdf_bytes = await pptx_to_pdf(file_bytes)
                images = await pdf_to_images(pdf_bytes)
            elif job.source_format == "pdf":
                images = await pdf_to_images(file_bytes)
            else:
                img_bytes = await prepare_image(file_bytes)
                images = [img_bytes]

            # VLM semantic 호출
            vlm_client = VLMClient(config)
            try:
                doc_result: DocumentResult = await vlm_client.process_document(images)
            finally:
                await vlm_client.close()

            result = ConvertResult(
                text=doc_result.text,
                format="md",
                pages=doc_result.total_pages,
                file_name=job.file_name,
                source_format=job.source_format,
                route="vlm",
                quality=Quality(
                    total_chars=len(doc_result.text),
                    chars_per_page=len(doc_result.text) / doc_result.total_pages if doc_result.total_pages > 0 else 0,
                    total_pages=doc_result.total_pages,
                    failed_pages=doc_result.failed_pages,
                    confidence=doc_result.confidence,
                    total_batches=doc_result.total_batches,
                    failed_batches=doc_result.failed_batches,
                    method="semantic",
                ),
            )
            await store.save_result(job.id, result)

            # 메타 추출
            meta = await _extract_meta(result.text, meta_extractor, config)
            if hasattr(store, "save_meta") and meta:
                await store.save_meta(job.id, meta, META_PROMPT_VERSION)

    except Exception as e:
        await store.save_error(job.id, str(e))
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/test_worker.py -v`
Expected: 7 passed

- [ ] **Step 5: 커밋**

```bash
git add worker.py tests/test_worker.py
git commit -m "feat: worker meta extraction after conversion + VLM log support"
```

---

### Task 7: API — requested_by + format=text + DB lifecycle

**Files:**
- Modify: `app.py`
- Modify: `tests/test_app.py`

- [ ] **Step 1: 테스트 추가**

```python
# tests/test_app.py 에 추가
@pytest.mark.asyncio
async def test_convert_with_requested_by(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch("app.process_job", new_callable=AsyncMock):
            resp = await client.post(
                "/convert?requested_by=cortex-api",
                files={"file": ("test.docx", b"content", "application/octet-stream")},
            )
    assert resp.status_code == 200
    data = resp.json()
    assert "job_id" in data


@pytest.mark.asyncio
async def test_result_format_text(app):
    """?format=text → plain text 반환"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 먼저 job 생성
        with patch("app.process_job", new_callable=AsyncMock):
            create_resp = await client.post(
                "/convert",
                files={"file": ("test.docx", b"content", "application/octet-stream")},
            )
        job_id = create_resp.json()["job_id"]

        # store에 직접 결과 세팅 (InMemoryJobStore)
        store = app.state.store
        from models import ConvertResult, Quality
        result = ConvertResult(
            text="# Hello World", format="md", pages=1,
            file_name="test.docx", source_format="docx", route="extract",
            quality=Quality(total_chars=13, chars_per_page=13, total_pages=1, failed_pages=0, confidence="high"),
        )
        await store.save_result(job_id, result)

        resp = await client.get(f"/result/{job_id}?format=text")

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "text/markdown; charset=utf-8"
    assert resp.text == "# Hello World"
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/test_app.py -v -k "requested_by or format_text"`
Expected: FAIL

- [ ] **Step 3: app.py 수정**

주요 변경:
1. `/convert`에 `requested_by` 쿼리 파라미터 추가
2. `store.create()`에 `file_size`, `method`, `requested_by` 전달
3. `/result/{job_id}`에 `format` 쿼리 파라미터 추가 → `text`이면 plain text 반환
4. `/result/{job_id}` JSON 응답에 `meta` 필드 추가

```python
# app.py
import asyncio
import logging
from typing import List

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import PlainTextResponse

from config import Config
from job_store import InMemoryJobStore, JobStore
from router import UnsupportedFormatError, detect_route
from worker import process_job

logger = logging.getLogger(__name__)


async def _safe_process(job, file_bytes, route, store, config, meta_extractor=None):
    """create_task용 래퍼. 미처리 예외를 로깅."""
    try:
        await process_job(job, file_bytes, route, store, config, meta_extractor=meta_extractor)
    except Exception:
        logger.exception("Unhandled error in job %s", job.id)


def create_app(store: JobStore | None = None, config: Config | None = None) -> FastAPI:
    config = config or Config()
    store = store or InMemoryJobStore()

    app = FastAPI(title="Forge — Document Converter", version="0.3.0")

    app.state.store = store
    app.state.config = config

    @app.on_event("startup")
    async def startup():
        if config.database_url:
            import asyncpg
            from job_store import PostgresJobStore, VLMLogStore
            pool = await asyncpg.create_pool(config.database_url)
            app.state.pool = pool
            app.state.store = PostgresJobStore(pool)
            app.state.vlm_log_store = VLMLogStore(pool)
            # MetaExtractor singleton
            from meta import MetaExtractor
            app.state.meta_extractor = MetaExtractor(config)

    @app.on_event("shutdown")
    async def shutdown():
        if hasattr(app.state, "pool"):
            await app.state.pool.close()
        if hasattr(app.state, "meta_extractor"):
            await app.state.meta_extractor.close()

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.post("/convert")
    async def convert(
        file: UploadFile = File(...),
        route: str | None = Query(None, pattern="^(extract|vlm)$"),
        requested_by: str | None = Query(None),
    ):
        file_bytes = await file.read()
        file_name = file.filename or "unknown"

        if len(file_bytes) > config.max_file_size:
            raise HTTPException(status_code=413, detail=f"File too large: max {config.max_file_size} bytes")

        try:
            detected_route, source_format = detect_route(file_name, file_bytes, route_override=route)
        except UnsupportedFormatError as e:
            raise HTTPException(status_code=400, detail=str(e))

        method = "semantic" if detected_route == "vlm" else "extract"
        job = await store.create(
            file_name, source_format, detected_route,
            file_size=len(file_bytes), method=method, requested_by=requested_by,
        )
        meta_ext = getattr(app.state, "meta_extractor", None)
        asyncio.create_task(_safe_process(job, file_bytes, detected_route, store, config, meta_extractor=meta_ext))

        return {"job_id": job.id, "status": job.status}

    @app.get("/result/{job_id}")
    async def result(
        job_id: str,
        format: str | None = Query(None, alias="format"),
    ):
        job = await store.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")

        # ?format=text → plain text 반환
        if format == "text" and job.result:
            return PlainTextResponse(
                content=job.result.text,
                media_type="text/markdown",
            )

        return {
            "status": job.status,
            "result": job.result.model_dump() if job.result else None,
            "meta": job.meta if hasattr(job, "meta") else {},
            "error": job.error,
        }

    @app.post("/batch")
    async def batch(
        files: List[UploadFile] = File(...),
        route: str | None = Query(None, pattern="^(extract|vlm)$"),
        requested_by: str | None = Query(None),
    ):
        jobs = []
        for file in files:
            file_bytes = await file.read()
            file_name = file.filename or "unknown"

            if len(file_bytes) > config.max_file_size:
                jobs.append({"file_name": file_name, "error": f"File too large: max {config.max_file_size} bytes"})
                continue

            try:
                detected_route, source_format = detect_route(file_name, file_bytes, route_override=route)
            except UnsupportedFormatError as e:
                jobs.append({"file_name": file_name, "error": str(e)})
                continue

            method = "semantic" if detected_route == "vlm" else "extract"
            job = await store.create(
                file_name, source_format, detected_route,
                file_size=len(file_bytes), method=method, requested_by=requested_by,
            )
            meta_ext = getattr(app.state, "meta_extractor", None)
        asyncio.create_task(_safe_process(job, file_bytes, detected_route, store, config, meta_extractor=meta_ext))
            jobs.append({"file_name": file_name, "job_id": job.id, "status": job.status})

        return {"jobs": jobs}

    return app


app = create_app()
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/test_app.py -v`
Expected: 전체 통과

- [ ] **Step 5: 전체 테스트 실행**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/ -v`
Expected: 전체 통과

- [ ] **Step 6: .env.example 최종 확인, Dockerfile 변경 불필요 확인**

- [ ] **Step 7: 커밋**

```bash
git add app.py tests/test_app.py
git commit -m "feat: requested_by param, ?format=text endpoint, meta in result"
```

---
