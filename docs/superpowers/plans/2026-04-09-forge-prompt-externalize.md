# Forge 프롬프트 외부화 + 버전 관리 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 프롬프트를 DB에 저장하여 코드 배포 없이 교체하고, 버전 이력을 보존하여 Job별 프롬프트 추적이 가능하게 한다.

**Architecture:** `forge_prompts` 테이블에 프롬프트 저장. `PromptStore`로 CRUD. startup 시 메모리 캐시 로드. vlm.py/meta.py에서 하드코딩 제거 → 외부 주입. 관리 API로 새 버전 등록.

**Tech Stack:** Python 3.11, FastAPI, asyncpg, PostgreSQL, pytest, pytest-asyncio

---

## File Map

| 파일 | 역할 | Task |
|------|------|------|
| `schema.sql` | `forge_prompts` 테이블 추가 | 1 |
| `job_store.py` | `PromptStore` 클래스 추가 | 2 |
| `vlm.py` | `SEMANTIC_PROMPT` 하드코딩 제거 → 파라미터 주입 | 3 |
| `meta.py` | `META_PROMPT` 하드코딩 제거 → 파라미터 주입 | 3 |
| `worker.py` | prompts 캐시에서 로드 → 전달 + 버전 기록 | 4 |
| `admin.py` | `/prompts` 3개 엔드포인트 추가 | 5 |
| `app.py` | startup 프롬프트 로드/시딩 + 캐시 | 6 |
| `tests/` | 각 Task별 테스트 | 1-6 |

---

### Task 1: DB 스키마

**Files:**
- Modify: `schema.sql`

- [ ] **Step 1: schema.sql에 forge_prompts 추가**

schema.sql 끝에 추가:

```sql
CREATE TABLE IF NOT EXISTS forge_prompts (
    id          SERIAL PRIMARY KEY,
    type        VARCHAR(30) NOT NULL,
    version     INT NOT NULL,
    text        TEXT NOT NULL,
    is_active   BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_forge_prompts_active
    ON forge_prompts(type) WHERE is_active = TRUE;
```

- [ ] **Step 2: 실행 중인 DB에 마이그레이션 적용**

```bash
cd C:/workspace/prj20060203/Forge && python -c "
import asyncio, asyncpg
async def migrate():
    conn = await asyncpg.connect('postgresql://postgres:postgres@localhost:5556/graphrag')
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS forge_prompts (
            id          SERIAL PRIMARY KEY,
            type        VARCHAR(30) NOT NULL,
            version     INT NOT NULL,
            text        TEXT NOT NULL,
            is_active   BOOLEAN DEFAULT TRUE,
            created_at  TIMESTAMPTZ DEFAULT NOW()
        )
    ''')
    await conn.execute('''
        CREATE UNIQUE INDEX IF NOT EXISTS idx_forge_prompts_active
            ON forge_prompts(type) WHERE is_active = TRUE
    ''')
    print('Migration done')
    await conn.close()
asyncio.run(migrate())
"
```

- [ ] **Step 3: 커밋**

```bash
git add schema.sql
git commit -m "feat: forge_prompts table for prompt versioning"
```

---

### Task 2: PromptStore

**Files:**
- Modify: `job_store.py`
- Create: `tests/test_prompt_store.py`

- [ ] **Step 1: 테스트 작성**

```python
# tests/test_prompt_store.py
import pytest
from unittest.mock import AsyncMock
from job_store import PromptStore


@pytest.fixture
def mock_pool():
    return AsyncMock()


@pytest.fixture
def store(mock_pool):
    return PromptStore(mock_pool)


@pytest.mark.asyncio
async def test_get_active(store, mock_pool):
    mock_pool.fetchrow = AsyncMock(return_value={
        "id": 1, "type": "semantic", "version": 1,
        "text": "prompt text", "is_active": True,
        "created_at": "2026-04-09T00:00:00+00:00",
    })
    result = await store.get_active("semantic")
    assert result["type"] == "semantic"
    assert result["text"] == "prompt text"


@pytest.mark.asyncio
async def test_get_active_not_found(store, mock_pool):
    mock_pool.fetchrow = AsyncMock(return_value=None)
    result = await store.get_active("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_list_all(store, mock_pool):
    mock_pool.fetch = AsyncMock(return_value=[
        {"id": 2, "type": "semantic", "version": 2, "text": "v2", "is_active": True, "created_at": "2026-04-09"},
        {"id": 1, "type": "semantic", "version": 1, "text": "v1", "is_active": False, "created_at": "2026-04-08"},
    ])
    result = await store.list_all()
    assert len(result) == 2


@pytest.mark.asyncio
async def test_create_version(store, mock_pool):
    mock_pool.fetchval = AsyncMock(return_value=1)  # current max version
    mock_pool.execute = AsyncMock()
    mock_pool.fetchrow = AsyncMock(return_value={
        "id": 2, "type": "semantic", "version": 2,
        "text": "new prompt", "is_active": True,
        "created_at": "2026-04-09T00:00:00+00:00",
    })
    result = await store.create_version("semantic", "new prompt")
    assert result["version"] == 2
    assert result["is_active"] is True


@pytest.mark.asyncio
async def test_create_version_first(store, mock_pool):
    """첫 프롬프트 등록 (기존 없음)"""
    mock_pool.fetchval = AsyncMock(return_value=None)  # no existing
    mock_pool.execute = AsyncMock()
    mock_pool.fetchrow = AsyncMock(return_value={
        "id": 1, "type": "meta_extract", "version": 1,
        "text": "first prompt", "is_active": True,
        "created_at": "2026-04-09T00:00:00+00:00",
    })
    result = await store.create_version("meta_extract", "first prompt")
    assert result["version"] == 1
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/test_prompt_store.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: job_store.py에 PromptStore 추가**

`VLMLogStore` 클래스 뒤에 추가:

```python
class PromptStore:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def get_active(self, prompt_type: str) -> dict | None:
        row = await self._pool.fetchrow(
            "SELECT * FROM forge_prompts WHERE type = $1 AND is_active = TRUE",
            prompt_type,
        )
        if row is None:
            return None
        return dict(row)

    async def list_all(self) -> list[dict]:
        rows = await self._pool.fetch(
            "SELECT * FROM forge_prompts ORDER BY type, version DESC"
        )
        return [dict(r) for r in rows]

    async def create_version(self, prompt_type: str, text: str) -> dict:
        # 현재 최대 버전 조회
        max_version = await self._pool.fetchval(
            "SELECT MAX(version) FROM forge_prompts WHERE type = $1",
            prompt_type,
        )
        new_version = (max_version or 0) + 1

        # 기존 활성 비활성화
        await self._pool.execute(
            "UPDATE forge_prompts SET is_active = FALSE WHERE type = $1 AND is_active = TRUE",
            prompt_type,
        )

        # 새 버전 INSERT
        row = await self._pool.fetchrow(
            """INSERT INTO forge_prompts (type, version, text, is_active)
               VALUES ($1, $2, $3, TRUE) RETURNING *""",
            prompt_type, new_version, text,
        )
        return dict(row)

    async def seed_if_empty(self, prompt_type: str, default_text: str) -> None:
        """DB에 해당 type이 없으면 v1으로 시딩."""
        exists = await self._pool.fetchval(
            "SELECT COUNT(*) FROM forge_prompts WHERE type = $1", prompt_type
        )
        if exists == 0:
            await self._pool.fetchrow(
                """INSERT INTO forge_prompts (type, version, text, is_active)
                   VALUES ($1, 1, $2, TRUE) RETURNING *""",
                prompt_type, default_text,
            )
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/test_prompt_store.py -v`
Expected: 5 passed

- [ ] **Step 5: 커밋**

```bash
git add job_store.py tests/test_prompt_store.py
git commit -m "feat: PromptStore — CRUD + versioning + seed_if_empty"
```

---

### Task 3: vlm.py + meta.py 프롬프트 외부 주입

**Files:**
- Modify: `vlm.py`
- Modify: `meta.py`
- Modify: `tests/test_vlm.py`
- Modify: `tests/test_meta.py`

- [ ] **Step 1: vlm.py 수정 — SEMANTIC_PROMPT 하드코딩을 기본값으로 유지하되 파라미터 주입 가능하게**

`vlm.py`에서 `SEMANTIC_PROMPT` 변수는 유지 (기본값/시딩용). `VLMClient.__init__`에 `prompt` 파라미터 추가:

현재:
```python
class VLMClient:
    def __init__(self, config: Config):
```

변경:
```python
class VLMClient:
    def __init__(self, config: Config, prompt: str | None = None):
        self.prompt = prompt or SEMANTIC_PROMPT
```

`process_batch`에서 `SEMANTIC_PROMPT` 대신 `self.prompt` 사용:

현재:
```python
content = [{"type": "text", "text": SEMANTIC_PROMPT}]
```

변경:
```python
content = [{"type": "text", "text": self.prompt}]
```

- [ ] **Step 2: meta.py 수정 — META_PROMPT 파라미터 주입**

`MetaExtractor.__init__`에 `prompt` 파라미터 추가:

현재:
```python
class MetaExtractor:
    def __init__(self, config: Config):
```

변경:
```python
class MetaExtractor:
    def __init__(self, config: Config, prompt: str | None = None):
        self.prompt = prompt or META_PROMPT
```

`extract`에서 `META_PROMPT` 대신 `self.prompt` 사용:

현재:
```python
{"role": "user", "content": f"{META_PROMPT}\n\n---\n\n{truncated}"}
```

변경:
```python
{"role": "user", "content": f"{self.prompt}\n\n---\n\n{truncated}"}
```

- [ ] **Step 3: 기존 테스트 통과 확인 (기본값 fallback이라 깨지면 안 됨)**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/test_vlm.py tests/test_meta.py -v`
Expected: 전부 통과 (기본값 fallback)

- [ ] **Step 4: 커밋**

```bash
git add vlm.py meta.py
git commit -m "feat: VLMClient + MetaExtractor accept external prompt parameter"
```

---

### Task 4: Worker — 프롬프트 캐시에서 로드 + 버전 기록

**Files:**
- Modify: `worker.py`
- Modify: `tests/test_worker.py`

- [ ] **Step 1: worker.py 수정**

`PROMPT_VERSION`과 `META_PROMPT_VERSION` 상수 제거. `process_job`에 `prompts` 파라미터 추가:

```python
async def process_job(
    job: Job,
    file_bytes: bytes,
    route: str,
    store: JobStore,
    config: Config,
    meta_extractor: MetaExtractor | None = None,
    vlm_log_store=None,
    prompts: dict | None = None,
) -> None:
```

`prompts`는 `{"semantic": {"text": "...", "version": 2}, "meta_extract": {"text": "...", "version": 1}}` 형태.

VLM 호출 시:
```python
# 프롬프트 로드
semantic_prompt = prompts.get("semantic", {}) if prompts else {}
prompt_text = semantic_prompt.get("text")
prompt_ver = f"semantic-v{semantic_prompt.get('version', '?')}" if semantic_prompt else "semantic-v?"

# VLM 호출
vlm_client = VLMClient(config, prompt=prompt_text)
```

`save_result` 후 `prompt_version` 기록:
- extract 경로: `prompt_version`은 None (프롬프트 안 씀)
- vlm 경로: `prompt_version = "semantic-v{N}"`

메타 추출 시:
```python
meta_prompt = prompts.get("meta_extract", {}) if prompts else {}
meta_text = meta_prompt.get("text")
meta_ver = f"meta_extract-v{meta_prompt.get('version', '?')}" if meta_prompt else "meta_extract-v?"
```

`_extract_meta`에서 MetaExtractor 임시 생성 시에도 prompt 전달:
```python
if extractor is None:
    extractor = MetaExtractor(config, prompt=meta_text)
    should_close = True
```

`save_meta` 호출 시 `meta_ver` 전달.

- [ ] **Step 2: tests/test_worker.py에서 prompts 파라미터 추가**

기존 `process_job` 호출에 `prompts=None` 추가 (기본값이라 기존 테스트 깨지지 않아야 함).

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/test_worker.py -v`
Expected: 전부 통과

- [ ] **Step 3: 커밋**

```bash
git add worker.py tests/test_worker.py
git commit -m "feat: worker loads prompts from cache, records version per job"
```

---

### Task 5: Admin API — /prompts 엔드포인트

**Files:**
- Modify: `admin.py`
- Create: `tests/test_prompt_api.py`

- [ ] **Step 1: 테스트 작성**

```python
# tests/test_prompt_api.py
import pytest
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport
from app import create_app
from config import Config


@pytest.fixture
def app():
    return create_app(config=Config(forge_api_key=""))


@pytest.mark.asyncio
async def test_get_prompts_without_db(app):
    """InMemoryJobStore일 때 501"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/prompts")
    assert resp.status_code == 501


@pytest.mark.asyncio
async def test_get_active_prompt_without_db(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/prompts/semantic/active")
    assert resp.status_code == 501
```

- [ ] **Step 2: admin.py에 /prompts 엔드포인트 3개 추가**

`create_admin_router` 함수 내 기존 엔드포인트 뒤에:

```python
    @router.get("/prompts", summary="프롬프트 전체 목록", tags=["프롬프트"])
    async def list_prompts():
        """전체 프롬프트 버전 이력."""
        prompt_store = getattr(app_state, "prompt_store", None)
        if prompt_store is None:
            raise HTTPException(status_code=501, detail="PromptStore not available")
        prompts = await prompt_store.list_all()
        return {"prompts": prompts}

    @router.get("/prompts/{prompt_type}/active", summary="활성 프롬프트 조회", tags=["프롬프트"])
    async def get_active_prompt(prompt_type: str):
        """현재 활성 프롬프트. type: semantic 또는 meta_extract."""
        prompt_store = getattr(app_state, "prompt_store", None)
        if prompt_store is None:
            raise HTTPException(status_code=501, detail="PromptStore not available")
        prompt = await prompt_store.get_active(prompt_type)
        if prompt is None:
            raise HTTPException(status_code=404, detail=f"No active prompt for type: {prompt_type}")
        return prompt

    @router.post("/prompts", summary="새 프롬프트 버전 등록", tags=["프롬프트"])
    async def create_prompt(body: dict):
        """새 프롬프트 등록. 기존 활성 버전 비활성화. body: {type, text}"""
        prompt_store = getattr(app_state, "prompt_store", None)
        if prompt_store is None:
            raise HTTPException(status_code=501, detail="PromptStore not available")
        prompt_type = body.get("type")
        text = body.get("text")
        if prompt_type not in ("semantic", "meta_extract"):
            raise HTTPException(status_code=400, detail="type must be 'semantic' or 'meta_extract'")
        if not text:
            raise HTTPException(status_code=400, detail="text is required")
        result = await prompt_store.create_version(prompt_type, text)
        # 메모리 캐시 갱신
        if hasattr(app_state, "prompts"):
            app_state.prompts[prompt_type] = {"text": result["text"], "version": result["version"]}
        return result
```

- [ ] **Step 3: 테스트 통과 확인**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/test_prompt_api.py -v`
Expected: 통과

- [ ] **Step 4: 커밋**

```bash
git add admin.py tests/test_prompt_api.py
git commit -m "feat: /prompts API — list, get active, create version"
```

---

### Task 6: App startup — 프롬프트 로드/시딩 + 캐시 + worker 연결

**Files:**
- Modify: `app.py`

- [ ] **Step 1: app.py lifespan에 프롬프트 로드 추가**

lifespan startup 블록에서, `MetaExtractor` 생성 후:

```python
        # PromptStore + 프롬프트 시딩/로드
        if config.database_url:
            from job_store import PromptStore
            from vlm import SEMANTIC_PROMPT
            from meta import META_PROMPT
            a.state.prompt_store = PromptStore(pool)
            await a.state.prompt_store.seed_if_empty("semantic", SEMANTIC_PROMPT)
            await a.state.prompt_store.seed_if_empty("meta_extract", META_PROMPT)

            # 활성 프롬프트 캐시
            semantic = await a.state.prompt_store.get_active("semantic")
            meta_ext = await a.state.prompt_store.get_active("meta_extract")
            a.state.prompts = {
                "semantic": {"text": semantic["text"], "version": semantic["version"]} if semantic else {},
                "meta_extract": {"text": meta_ext["text"], "version": meta_ext["version"]} if meta_ext else {},
            }
```

- [ ] **Step 2: _safe_process에 prompts 전달**

```python
async def _safe_process(job, file_bytes, route, store, config, meta_extractor=None, vlm_log_store=None, prompts=None):
    try:
        await process_job(job, file_bytes, route, store, config, meta_extractor=meta_extractor, vlm_log_store=vlm_log_store, prompts=prompts)
    except Exception:
        logger.exception("Unhandled error in job %s", job.id)
```

create_task 호출부 (convert, batch 둘 다):
```python
        prompts_cache = getattr(app.state, "prompts", None)
        asyncio.create_task(_safe_process(job, file_bytes, detected_route, current_store, config, meta_extractor=meta_ext, vlm_log_store=vlm_logs, prompts=prompts_cache))
```

- [ ] **Step 3: MetaExtractor 생성 시에도 프롬프트 주입**

lifespan에서 MetaExtractor 생성 부분:

현재:
```python
        a.state.meta_extractor = MetaExtractor(config)
```

변경 (DB 있을 때):
```python
        # MetaExtractor에 DB 프롬프트 주입
        meta_prompt_text = a.state.prompts.get("meta_extract", {}).get("text") if hasattr(a.state, "prompts") else None
        a.state.meta_extractor = MetaExtractor(config, prompt=meta_prompt_text)
```

DB 없을 때 (기존 기본값 사용):
```python
        from meta import MetaExtractor
        a.state.meta_extractor = MetaExtractor(config)
```

- [ ] **Step 4: 전체 테스트 실행**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/ -v`
Expected: 전체 통과

- [ ] **Step 5: 커밋**

```bash
git add app.py
git commit -m "feat: startup prompt seeding/loading + cache + worker injection"
```

---
