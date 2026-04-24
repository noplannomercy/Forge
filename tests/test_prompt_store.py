import pytest
from unittest.mock import AsyncMock
from job_store import InMemoryPromptStore, PromptStore, seed_prompts


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
    mock_pool.fetchval = AsyncMock(return_value=1)
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
    mock_pool.fetchval = AsyncMock(return_value=None)
    mock_pool.execute = AsyncMock()
    mock_pool.fetchrow = AsyncMock(return_value={
        "id": 1, "type": "meta_extract", "version": 1,
        "text": "first prompt", "is_active": True,
        "created_at": "2026-04-09T00:00:00+00:00",
    })
    result = await store.create_version("meta_extract", "first prompt")
    assert result["version"] == 1


# ---------------------------------------------------------------------------
# T7: reverse_doc prompt seed + InMemoryPromptStore parity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reverse_doc_seed_upserts():
    """seed_prompts(InMemoryPromptStore) 이후 reverse_doc 활성 프롬프트가 로드된다."""
    store = InMemoryPromptStore()
    await seed_prompts(store)
    active = await store.get_active("reverse_doc")
    assert active is not None
    assert active["type"] == "reverse_doc"
    assert active["is_active"] is True
    assert active["version"] == 1
    assert active["text"].startswith("# 역문서")
    assert len(active["text"]) > 0


@pytest.mark.asyncio
async def test_reverse_doc_seed_idempotent():
    """seed_prompts()를 두 번 호출해도 중복 생성되지 않는다 (ensure_latest_prompt 기반 — 정규화 비교로 동일 내용 no-op)."""
    store = InMemoryPromptStore()
    await seed_prompts(store)
    await seed_prompts(store)
    active = await store.get_active("reverse_doc")
    assert active["version"] == 1
    all_versions = [p for p in await store.list_all() if p["type"] == "reverse_doc"]
    assert len(all_versions) == 1


@pytest.mark.asyncio
async def test_reverse_doc_prompt_contains_7_sections():
    """시드된 프롬프트 텍스트가 필수 7섹션 헤더를 모두 포함한다."""
    store = InMemoryPromptStore()
    await seed_prompts(store)
    active = await store.get_active("reverse_doc")
    text = active["text"]
    required_sections = [
        "## 업무목적",
        "## 처리흐름",
        "## 입력/출력",
        "## 규칙/예외",
        "## 근거",
        "## 추적성",
        "## 관련업무",
    ]
    for section in required_sections:
        assert section in text, f"missing section header: {section}"


# ---------------------------------------------------------------------------
# Normalization helper
# ---------------------------------------------------------------------------


def test_normalize_prompt_text_strips_trailing_newline():
    from job_store import _normalize_prompt_text
    assert _normalize_prompt_text("hello\n") == "hello"
    assert _normalize_prompt_text("hello\n\n\n") == "hello"


def test_normalize_prompt_text_converts_crlf_to_lf():
    from job_store import _normalize_prompt_text
    assert _normalize_prompt_text("a\r\nb\r\nc") == "a\nb\nc"


def test_normalize_prompt_text_preserves_real_content():
    from job_store import _normalize_prompt_text
    # 내부 줄바꿈은 유지, 내용 구분은 훼손되지 않음
    assert _normalize_prompt_text("line1\nline2\nline3") == "line1\nline2\nline3"
    # 중간 공백/탭은 보존
    assert _normalize_prompt_text("a  b\tc") == "a  b\tc"


# ---------------------------------------------------------------------------
# ensure_latest_prompt — 기본 동작 3건
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ensure_latest_prompt_creates_when_empty():
    from job_store import ensure_latest_prompt
    store = InMemoryPromptStore()
    await ensure_latest_prompt(store, "demo", "text v1")
    active = await store.get_active("demo")
    assert active is not None
    assert active["version"] == 1
    assert active["text"] == "text v1"
    assert active["is_active"] is True


@pytest.mark.asyncio
async def test_ensure_latest_prompt_noop_when_same():
    from job_store import ensure_latest_prompt
    store = InMemoryPromptStore()
    await ensure_latest_prompt(store, "demo", "text v1")
    await ensure_latest_prompt(store, "demo", "text v1")
    all_versions = [p for p in await store.list_all() if p["type"] == "demo"]
    assert len(all_versions) == 1
    assert all_versions[0]["version"] == 1


@pytest.mark.asyncio
async def test_ensure_latest_prompt_upgrades_when_different():
    from job_store import ensure_latest_prompt
    store = InMemoryPromptStore()
    await ensure_latest_prompt(store, "demo", "text v1")
    await ensure_latest_prompt(store, "demo", "text v2 different")

    all_versions = [p for p in await store.list_all() if p["type"] == "demo"]
    assert len(all_versions) == 2
    active = await store.get_active("demo")
    assert active["version"] == 2
    assert active["text"] == "text v2 different"
    # v1은 비활성
    v1 = next(p for p in all_versions if p["version"] == 1)
    assert v1["is_active"] is False


# ---------------------------------------------------------------------------
# ensure_latest_prompt — 정규화 엣지 케이스 3건
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ensure_latest_prompt_ignores_trailing_newline():
    """DB에 'text', 파일이 'text\\n' → 정규화 후 동일 → no-op."""
    from job_store import ensure_latest_prompt
    store = InMemoryPromptStore()
    await ensure_latest_prompt(store, "demo", "text")
    await ensure_latest_prompt(store, "demo", "text\n")
    await ensure_latest_prompt(store, "demo", "text\n\n\n")
    all_versions = [p for p in await store.list_all() if p["type"] == "demo"]
    assert len(all_versions) == 1


@pytest.mark.asyncio
async def test_ensure_latest_prompt_ignores_crlf_diff():
    """DB에 'a\\nb', 파일이 'a\\r\\nb' → 정규화 후 동일 → no-op (Windows autocrlf)."""
    from job_store import ensure_latest_prompt
    store = InMemoryPromptStore()
    await ensure_latest_prompt(store, "demo", "a\nb")
    await ensure_latest_prompt(store, "demo", "a\r\nb")
    all_versions = [p for p in await store.list_all() if p["type"] == "demo"]
    assert len(all_versions) == 1


@pytest.mark.asyncio
async def test_ensure_latest_prompt_detects_real_content_change():
    """정규화가 실제 내용 변화를 가리지 않는지 검증."""
    from job_store import ensure_latest_prompt
    store = InMemoryPromptStore()
    await ensure_latest_prompt(store, "demo", "hello")
    await ensure_latest_prompt(store, "demo", "hello world")  # 내용 추가 → 신규 버전
    all_versions = [p for p in await store.list_all() if p["type"] == "demo"]
    assert len(all_versions) == 2
    active = await store.get_active("demo")
    assert active["text"] == "hello world"


# ---------------------------------------------------------------------------
# seed_prompts auto-upgrade integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seed_prompts_auto_upgrades_when_file_changes(monkeypatch):
    """파일 내용이 DB active와 다르면 seed_prompts가 새 버전 생성."""
    from job_store import seed_prompts, InMemoryPromptStore

    store = InMemoryPromptStore()
    # 1회차: 현재 파일 내용으로 시드
    await seed_prompts(store)
    v1_text = (await store.get_active("reverse_doc"))["text"]

    # 파일 로더를 mock — 다른 텍스트 리턴
    monkeypatch.setattr(
        "job_store._load_reverse_doc_prompt",
        lambda: v1_text + "\n\n# 추가된 내용\n",
    )
    await seed_prompts(store)

    active = await store.get_active("reverse_doc")
    assert active["version"] == 2
    assert "추가된 내용" in active["text"]

    all_versions = [p for p in await store.list_all() if p["type"] == "reverse_doc"]
    assert len(all_versions) == 2


@pytest.mark.asyncio
async def test_seed_prompts_noop_on_same_content():
    """동일 내용으로 2회 호출 → version 1 유지 (정규화 덕분)."""
    from job_store import seed_prompts, InMemoryPromptStore

    store = InMemoryPromptStore()
    await seed_prompts(store)
    await seed_prompts(store)  # 같은 파일 두 번째 로드

    all_versions = [p for p in await store.list_all() if p["type"] == "reverse_doc"]
    assert len(all_versions) == 1
