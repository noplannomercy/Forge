# Revdoc Gate Simplification — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/reverse-doc` 게이트의 추적성 삼각 검사를 제거하고 프롬프트를 자유 서술로 완화하여 멀쩡한 LLM 출력이 게이트에서 탈락하는 문제를 해결한다. 동시에 프롬프트 파일 변경이 startup에 자동으로 DB 신규 버전으로 반영되도록 배포 로직을 정비한다.

**Architecture:** `revdoc/gate.py`의 3단계 검사(섹션 > 추적성 > 길이) → 2단계(섹션 > 길이)로 축소. `revdoc/prompts/reverse_doc_v1.md` → `reverse_doc.md`로 리네임 + 추적성 섹션 자유 서술로 완화 + min 800→500. `job_store.py`에 `_normalize_prompt_text`, `ensure_latest_prompt` 신규 헬퍼 추가하여 파일 SSoT 기반 자동 버전 업그레이드(+ CRLF/LF·trailing whitespace 정규화).

**Tech Stack:** Python 3.11+ / pytest + pytest-asyncio / FastAPI lifespan / asyncpg (PostgresPromptStore) / InMemoryPromptStore

**Spec:** `docs/superpowers/specs/2026-04-24-revdoc-gate-simplification-design.md`

---

## File Structure

**Modified**:
- `revdoc/gate.py` — 추적성 정규식·체크·피드백 삭제, `min_length` 800 → 500
- `revdoc/prompts/reverse_doc_v1.md` → `revdoc/prompts/reverse_doc.md` (rename + 내용 완화)
- `job_store.py` — `_normalize_prompt_text` + `ensure_latest_prompt` 추가, `_load_reverse_doc_prompt` 파일명 수정, `seed_prompts` docstring + 호출 경로 변경
- `tests/test_revdoc_gate.py` — 2 테스트 삭제, 6 테스트 수정, 헬퍼 수정
- `tests/test_prompt_store.py` — 6 테스트 추가 (기본 3 + 정규화 엣지 3)
- `tests/test_revdoc_generator.py` — `_valid_md()` 헬퍼 수정 (추적성 bullet 제거)
- `tests/test_revdoc_endpoint.py` — fixture 검토/조정 (필요 시)

**Created**: 없음.

**Deleted**: 없음 (파일은 rename만; 테스트 2개는 내부에서 삭제).

**Out of scope**: `revdoc/generator.py`, `revdoc/__init__.py`, `app.py`, `schema.sql`, 다른 extractor/worker/router.

---

## Task 1: `_normalize_prompt_text` 헬퍼 (TDD)

**Files:**
- Modify: `job_store.py` (신규 함수 추가, `_load_reverse_doc_prompt` 바로 위 위치)
- Test: `tests/test_prompt_store.py` (기존 파일 확장)

- [ ] **Step 1: 테스트 3개 작성**

`tests/test_prompt_store.py` 파일 끝에 추가:

```python
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
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
python -m pytest tests/test_prompt_store.py::test_normalize_prompt_text_strips_trailing_newline tests/test_prompt_store.py::test_normalize_prompt_text_converts_crlf_to_lf tests/test_prompt_store.py::test_normalize_prompt_text_preserves_real_content -v
```
Expected: 3 FAIL with `ImportError: cannot import name '_normalize_prompt_text' from 'job_store'`

- [ ] **Step 3: `_normalize_prompt_text` 구현**

`job_store.py` — `_load_reverse_doc_prompt()` 함수 바로 위에 추가:

```python
def _normalize_prompt_text(text: str) -> str:
    """줄바꿈·trailing whitespace 차이를 정규화하여 비교 안정성 확보.

    - CRLF → LF (Windows git autocrlf / editor 설정 차이 대응)
    - 파일 끝 trailing whitespace 제거 (editor save 차이 대응)

    `ensure_latest_prompt()`가 파일과 DB 텍스트를 비교할 때 사용하여
    환경 간 autocrlf 차이로 인한 "텍스트 다름" 오판을 방지한다.
    """
    return text.replace("\r\n", "\n").rstrip()
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
python -m pytest tests/test_prompt_store.py::test_normalize_prompt_text_strips_trailing_newline tests/test_prompt_store.py::test_normalize_prompt_text_converts_crlf_to_lf tests/test_prompt_store.py::test_normalize_prompt_text_preserves_real_content -v
```
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add job_store.py tests/test_prompt_store.py
git commit -m "feat(revdoc): add _normalize_prompt_text helper for cross-environment prompt comparison"
```

---

## Task 2: `ensure_latest_prompt` 헬퍼 (TDD)

**Files:**
- Modify: `job_store.py`
- Test: `tests/test_prompt_store.py`

- [ ] **Step 1: 기본 시나리오 테스트 3개 작성**

`tests/test_prompt_store.py` 파일 끝에 추가:

```python
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
```

- [ ] **Step 2: 정규화 엣지 테스트 3개 추가**

`tests/test_prompt_store.py` 파일 끝에 계속 추가:

```python
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
```

- [ ] **Step 3: 테스트 6개 실패 확인**

```bash
python -m pytest tests/test_prompt_store.py -v -k ensure_latest_prompt
```
Expected: 6 FAIL with `ImportError: cannot import name 'ensure_latest_prompt' from 'job_store'`

- [ ] **Step 4: `ensure_latest_prompt` 구현**

`job_store.py` — `_normalize_prompt_text` 바로 아래, `_load_reverse_doc_prompt()` 위에 추가:

```python
async def ensure_latest_prompt(store, prompt_type: str, current_text: str) -> None:
    """파일 내용이 DB active 버전과 다르면 새 버전 생성(auto-active).

    동작:
    * DB에 type=prompt_type인 active 프롬프트가 없으면 → create_version(v1).
    * 있고 _normalize_prompt_text로 비교해 동일하면 → no-op (부팅 시마다 불필요한
      write 방지, 줄바꿈/trailing whitespace 차이는 무시).
    * 있고 정규화 비교 결과 다르면 → create_version(v+1). `create_version`이
      기존 active를 자동 비활성화하므로 운영자 개입 불필요.

    `seed_if_empty`와 달리 파일 쪽이 단일 진실 공급원(SSoT)임을 가정.
    정규화 덕분에 `git config core.autocrlf` 설정 차이·editor trailing newline
    차이로 버전 번호가 부팅마다 증가하는 문제를 방지.
    """
    active = await store.get_active(prompt_type)
    if active is None:
        await store.create_version(prompt_type, current_text)
        return
    if _normalize_prompt_text(active["text"]) == _normalize_prompt_text(current_text):
        return
    await store.create_version(prompt_type, current_text)
```

- [ ] **Step 5: 테스트 6개 통과 확인**

```bash
python -m pytest tests/test_prompt_store.py -v -k ensure_latest_prompt
```
Expected: 6 PASS

- [ ] **Step 6: Commit**

```bash
git add job_store.py tests/test_prompt_store.py
git commit -m "feat(revdoc): add ensure_latest_prompt for file-driven prompt version upgrade"
```

---

## Task 3: 프롬프트 파일 rename + 내용 완화 + loader 경로 수정

**Files:**
- Rename: `revdoc/prompts/reverse_doc_v1.md` → `revdoc/prompts/reverse_doc.md`
- Modify: `revdoc/prompts/reverse_doc.md` (rename 후 내용 수정)
- Modify: `job_store.py:431-445` (`_load_reverse_doc_prompt` 경로)

- [ ] **Step 1: 파일 리네임 (git mv)**

```bash
git mv revdoc/prompts/reverse_doc_v1.md revdoc/prompts/reverse_doc.md
```

- [ ] **Step 2: `_load_reverse_doc_prompt` 경로 수정**

`job_store.py`의 `_load_reverse_doc_prompt()` 함수를 다음으로 교체:

```python
def _load_reverse_doc_prompt() -> str:
    """revdoc/prompts/reverse_doc.md 텍스트를 로드.

    파일 누락 시 RuntimeError. 하드코딩 fallback 없음 — 배포 누락 즉시 감지.
    """
    path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "revdoc",
        "prompts",
        "reverse_doc.md",
    )
    if not os.path.isfile(path):
        raise RuntimeError(f"reverse_doc prompt file missing: {path}")
    with open(path, encoding="utf-8") as f:
        return f.read()
```

변경점: docstring 파일명, `os.path.join`의 마지막 인자 `"reverse_doc_v1.md"` → `"reverse_doc.md"`.

- [ ] **Step 3: 프롬프트 내용 완화 — 추적성 섹션**

`revdoc/prompts/reverse_doc.md` 파일에서 `## 추적성` 섹션 내용 블록을 찾아 교체:

**삭제 대상** (36~42행 부근):
```
코드와 업무 규칙의 연결을 **Rule / Condition / Evidence 삼각**으로 최소 1건 명시:

- **Rule**: 업무 규칙명 (예: R-001 고객 등급 산출)
- **Condition**: 코드상의 조건 (예: IF total_amount > 1000 AND tier = 'GOLD')
- **Evidence**: 코드 위치 + 주석 (예: customer_tier.py:45, "High value customer upgrade")

삼각이 세 항목 모두 채워져야 한다. 하나라도 빠지면 게이트 실패로 간주된다.
```

**교체 내용**:
```
코드와 업무 규칙의 연결을 자유롭게 서술한다.
어떤 로직이 어떤 업무 규칙을 구현했는지, 근거를 어디서 확인할 수 있는지 등을 설명할 수 있다.
형식(목록/표/서술)은 자유.
```

- [ ] **Step 4: 프롬프트 내용 완화 — 제약 섹션**

같은 파일 `## 제약` 섹션에서:

**삭제 대상 (1행)**:
```
- 추적성은 Rule/Condition/Evidence 삼각으로 최소 1건.
```

**수정 대상**:
```
- 전체 길이 최소 800자.
```
→
```
- 전체 길이 최소 500자.
```

- [ ] **Step 5: 프롬프트 로더 동작 확인**

```bash
python -c "from job_store import _load_reverse_doc_prompt; t = _load_reverse_doc_prompt(); print(f'loaded: {len(t)} chars'); assert 'Rule / Condition / Evidence' not in t; assert '최소 500자' in t; print('content OK')"
```
Expected:
```
loaded: XXX chars
content OK
```

- [ ] **Step 6: 기존 prompt 시드 회귀 테스트 확인**

```bash
python -m pytest tests/test_prompt_store.py::test_reverse_doc_seed_upserts tests/test_prompt_store.py::test_reverse_doc_prompt_contains_7_sections -v
```
Expected: 2 PASS (seed는 아직 seed_if_empty 기반이지만 파일은 정상 로드됨)

- [ ] **Step 7: Commit**

```bash
git add revdoc/prompts/reverse_doc.md job_store.py
git commit -m "refactor(revdoc): rename reverse_doc_v1.md to reverse_doc.md + relax traceability to free-form"
```

---

## Task 4: `seed_prompts`를 `ensure_latest_prompt`로 전환

**Files:**
- Modify: `job_store.py:448-456` (`seed_prompts` 함수)
- Test: `tests/test_prompt_store.py` (신규 회귀 테스트 1건)

- [ ] **Step 1: 자동 업그레이드 회귀 테스트 작성**

`tests/test_prompt_store.py` 파일 끝에 추가:

```python
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
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
python -m pytest tests/test_prompt_store.py::test_seed_prompts_auto_upgrades_when_file_changes -v
```
Expected: FAIL — 현재 `seed_prompts`는 `seed_if_empty` 호출 → 두 번째 파일은 무시되어 version 2 생성 안 됨

- [ ] **Step 3: `seed_prompts` 구현 변경**

`job_store.py`의 `seed_prompts()` 함수를 다음으로 교체:

```python
async def seed_prompts(store) -> None:
    """reverse_doc 프롬프트를 최신 파일 내용으로 보장.

    설계 주의 — 시드 메커니즘 병행:
    * `reverse_doc`: `ensure_latest_prompt` 사용 — 내용 튜닝이 잦고 파일이 SSoT.
    * `semantic_batch`, `meta_extract`: 호출처(`app.py` lifespan)에서 `seed_if_empty`
      사용 — 초기 시드 후 변경은 Admin API(`POST /prompts`)로 관리. 자동 덮어쓰기가
      오히려 운영 리스크.

    두 패턴이 공존하는 것은 의도된 설계. 통합은 스코프 밖 (스펙 §2.2, §9 참조).
    """
    reverse_doc_text = _load_reverse_doc_prompt()
    await ensure_latest_prompt(store, "reverse_doc", reverse_doc_text)
```

- [ ] **Step 4: 신규 회귀 테스트 + 기존 회귀 테스트 모두 통과 확인**

```bash
python -m pytest tests/test_prompt_store.py -v
```
Expected: 전체 PASS (`test_reverse_doc_seed_idempotent` 포함 — `seed_if_empty` 기반이었지만 `ensure_latest_prompt`도 동일 내용은 no-op이라 테스트 의도 유지)

- [ ] **Step 5: Commit**

```bash
git add job_store.py tests/test_prompt_store.py
git commit -m "refactor(revdoc): switch seed_prompts to ensure_latest_prompt for file-driven upgrades"
```

---

## Task 5: `revdoc/gate.py` 단순화 + 게이트 테스트 재구성

**Files:**
- Modify: `revdoc/gate.py`
- Modify: `tests/test_revdoc_gate.py`

- [ ] **Step 1: 기존 게이트 테스트 2개 삭제**

`tests/test_revdoc_gate.py`에서 다음 두 함수 블록을 완전히 삭제:
- `def test_gate_fail_traceability_missing_rule(): ...`
- `def test_gate_accepts_korean_fullwidth_colon(): ...`

- [ ] **Step 2: `_valid_md()` 헬퍼 추적성 섹션 수정**

`tests/test_revdoc_gate.py`의 `_valid_md()` 함수 내부에서 `"## 추적성\n- Rule: ...\n- Condition: ...\n- Evidence: ...\n\n"` 부분을 교체:

**찾기**:
```python
        "## 추적성\n"
        "- Rule: R-001 고객 등급 산출\n"
        "- Condition: total_amount > 1000 AND tier = 'GOLD'\n"
        "- Evidence: customer_tier.py:45\n\n"
```

**교체**:
```python
        "## 추적성\n이 코드는 R-001 고객 등급 산출 업무 규칙을 구현하며, "
        "근거는 사내 정책 문서에서 확인할 수 있다.\n\n"
```

- [ ] **Step 3: `test_gate_pass_minimal` 수정**

해당 함수의 assertion 블록에서 다음 줄 **삭제**:

```python
    assert verdict.details["traceability"] == {
        "rule": True,
        "condition": True,
        "evidence": True,
    }
```

- [ ] **Step 4: `test_gate_fail_length_under_800` 이름·값 변경**

함수명 `test_gate_fail_length_under_800` → `test_gate_fail_length_under_500`.
함수 본문에서 `_valid_md(length=500)` → `_valid_md(length=300)`, `assert len(md) < 800` → `assert len(md) < 500`. assertion 블록의 `traceability` dict 관련 줄 **삭제**.

최종 함수 전체:

```python
def test_gate_fail_length_under_500():
    """All sections present, but length < 500 → length failure."""
    gate = RevdocGate()
    md = _valid_md(length=300)
    # Sanity: explicit floor so the test is not subtly broken by future
    # template growth pushing the un-padded body above 500.
    assert len(md) < 500
    verdict = gate.check(md)
    assert verdict.passed is False
    assert verdict.reason is not None
    assert "length" in verdict.reason
    assert verdict.feedback is not None
    # Earlier checks must have populated their details fields.
    assert verdict.details["missing_sections"] == []
    assert verdict.details["length"] == len(md)
```

- [ ] **Step 5: `test_gate_fail_priority_order` 수정 (2단계 우선순위)**

함수 본문 전체를 다음으로 교체:

```python
def test_gate_fail_priority_order():
    """When multiple checks would fail, section check wins (highest priority).

    Construct MD missing a section AND well under 500 chars.
    The reason must mention sections, not length.
    """
    gate = RevdocGate()
    md = (
        "## 업무목적\n짧다.\n\n"
        "## 입력/출력\n- a\n\n"
        "## 규칙/예외\n- b\n\n"
        "## 근거\n없음.\n\n"
        "## 추적성\n자유 서술.\n\n"
        "## 관련업무\n- e\n"
    )
    # Sanity: this MD should fail section + length checks.
    assert "## 처리흐름" not in md  # section missing
    assert len(md) < 500  # length short

    verdict = gate.check(md)
    assert verdict.passed is False
    assert verdict.reason is not None
    assert "missing" in verdict.reason
    # Priority: must NOT fall through to length.
    assert "length" not in verdict.reason
    # Details contract: only section-phase measurements present.
    assert "missing_sections" in verdict.details
    assert "처리흐름" in verdict.details["missing_sections"]
    assert "length" not in verdict.details
```

- [ ] **Step 6: `test_gate_feedback_populated_on_failure` 수정**

함수 본문 전체를 다음으로 교체 (triangle 케이스 삭제):

```python
def test_gate_feedback_populated_on_failure():
    """Every failure type must produce a non-empty, actionable feedback string."""
    gate = RevdocGate()

    # Failure type 1: missing section.
    md_no_section = _valid_md(length=900).replace("## 관련업무\n", "## XXX\n")
    v1 = gate.check(md_no_section)
    assert v1.passed is False
    assert v1.feedback is not None and len(v1.feedback) > 10
    assert "섹션" in v1.feedback or "section" in v1.feedback.lower()

    # Failure type 2: length.
    md_short = _valid_md(length=200)
    v2 = gate.check(md_short)
    assert v2.passed is False
    assert v2.feedback is not None and len(v2.feedback) > 10
    assert "짧" in v2.feedback or "길이" in v2.feedback or "자" in v2.feedback
```

- [ ] **Step 7: `test_gate_details_always_populated` 수정 (traceability 키 제거)**

함수 본문 전체를 다음으로 교체:

```python
def test_gate_details_always_populated():
    """``details`` dict is always a dict; its shape depends on which check fired.

    Contract:
    * On pass: both keys present — ``missing_sections`` (empty list), ``length`` (int).
    * On section failure: only ``missing_sections``.
    * On length failure: both keys.
    """
    gate = RevdocGate()

    # Pass.
    v_pass = gate.check(_valid_md(length=900))
    assert isinstance(v_pass.details, dict)
    assert set(v_pass.details.keys()) == {"missing_sections", "length"}

    # Section failure.
    v_sec = gate.check(_valid_md(length=900).replace("## 관련업무\n", "## XXX\n"))
    assert isinstance(v_sec.details, dict)
    assert set(v_sec.details.keys()) == {"missing_sections"}

    # Length failure.
    v_len = gate.check(_valid_md(length=200))
    assert isinstance(v_len.details, dict)
    assert set(v_len.details.keys()) == {"missing_sections", "length"}
```

- [ ] **Step 8: `test_gate_custom_min_length` 추적성 서술 수정**

인라인 MD의 `"## 추적성\nRule: x\nCondition: y\nEvidence: z\n"` 부분을 다음으로 교체:

```python
        "## 추적성\n자유 서술.\n"
```

함수의 나머지 로직(default min_length가 커스텀보다 큼을 검증) 그대로 유지. 단, default가 800→500으로 낮아지므로 인라인 MD 길이가 150자 정도라면 default 500으로도 reject됨 — 검증 그대로 동작.

- [ ] **Step 9: 게이트 테스트 실행 → 실패 확인 (구현 전)**

```bash
python -m pytest tests/test_revdoc_gate.py -v
```
Expected: 여러 FAIL — 수정된 테스트가 새 gate 동작을 기대하지만 gate는 아직 기존 3단계.
주요 실패 포인트: `test_gate_details_always_populated`(traceability 키 여전히 존재), `test_gate_fail_priority_order`(length 경로 분기 차이), 등.

- [ ] **Step 10: `revdoc/gate.py` 단순화**

`revdoc/gate.py` 파일 전체를 다음으로 교체:

```python
"""Gate for reverse-doc generation (REVDOC-05) — simplified 2026-04-24.

Validates the structural requirements of LLM-generated reverse-doc Markdown
output before accepting it. Checks two things in strict priority order:

1. **Required sections** — the 7 mandated headers must all be present,
   at any heading level (``##``, ``###``, …). The exact Korean header text
   must match (see :data:`REQUIRED_SECTIONS`).
2. **Minimum length** — total character count must be ≥ ``min_length``
   (default 500, matching ``reverse_doc.md`` constraint).

The gate short-circuits on the first failing check and returns a
:class:`GateVerdict` with a ``feedback`` string — an actionable,
Korean-language retry prompt hint that T9's generator will feed back
into the LLM on the next attempt.

``feedback`` is populated only on failure (``None`` on pass). ``details``
is populated progressively as checks run — callers should treat it as
"what we measured up to the point we stopped".

The gate is pure and synchronous. It does not touch the DB, the store,
or any Cortex/LightRAG machinery (cf. constraints C1/C6).

**Note** (simplification 2026-04-24): the previous traceability triangle
check (Rule/Condition/Evidence keyword regex) was removed. See
``docs/superpowers/specs/2026-04-24-revdoc-gate-simplification-design.md``
for rationale (regex-based traceability was a sham — real traceability
requires semantic verification, which we do not perform).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

REQUIRED_SECTIONS = [
    "업무목적",
    "처리흐름",
    "입력/출력",
    "규칙/예외",
    "근거",
    "추적성",
    "관련업무",
]


@dataclass
class GateVerdict:
    """Outcome of a :class:`RevdocGate` check.

    Attributes:
        passed: True iff every check was satisfied.
        details: Measurements collected up to the point the gate stopped.
            On pass, contains ``missing_sections`` (empty list) and
            ``length`` (int). On section failure: only ``missing_sections``.
            On length failure: both keys.
        reason: Short machine-oriented failure description, ``None`` on pass.
        feedback: Korean-language retry hint for the LLM, ``None`` on pass.
    """

    passed: bool
    details: dict = field(default_factory=dict)
    reason: str | None = None
    feedback: str | None = None


class RevdocGate:
    """Structural quality gate for reverse-doc MD output.

    The gate is stateless beyond its ``min_length`` configuration. A single
    instance may be reused across many :meth:`check` calls.
    """

    def __init__(self, min_length: int = 500):
        self.min_length = min_length

    def check(self, md: str) -> GateVerdict:
        """Evaluate ``md`` against the two structural checks.

        Returns a :class:`GateVerdict` with priority-ordered failure:
        sections > length. Never raises on empty input.
        """
        details: dict = {}

        # 1. Required sections — highest priority.
        missing: list[str] = []
        for section in REQUIRED_SECTIONS:
            pattern = rf"^#+\s*{re.escape(section)}"
            if not re.search(pattern, md, re.M):
                missing.append(section)
        details["missing_sections"] = missing
        if missing:
            return GateVerdict(
                passed=False,
                details=details,
                reason=f"sections missing: {missing}",
                feedback=(
                    f"출력에 다음 섹션이 누락되었다: {missing}. "
                    "정확한 헤더로 다시 생성하라."
                ),
            )

        # 2. Length.
        details["length"] = len(md)
        if len(md) < self.min_length:
            return GateVerdict(
                passed=False,
                details=details,
                reason=f"length {len(md)} < min {self.min_length}",
                feedback=(
                    f"본문이 짧다 ({len(md)}자). 각 섹션을 더 충분히 서술하라."
                ),
            )

        return GateVerdict(passed=True, details=details)
```

- [ ] **Step 11: 게이트 테스트 통과 확인**

```bash
python -m pytest tests/test_revdoc_gate.py -v
```
Expected: 모든 잔존 테스트 PASS (삭제된 2개 제외). 테스트 수: 9개 (기존 11개 - 2개 삭제).

- [ ] **Step 12: Commit**

```bash
git add revdoc/gate.py tests/test_revdoc_gate.py
git commit -m "refactor(revdoc): remove traceability check from gate + lower min_length to 500"
```

---

## Task 6: `test_revdoc_generator.py` / `test_revdoc_endpoint.py` fixture 재구성

**Files:**
- Modify: `tests/test_revdoc_generator.py`
- Modify: `tests/test_revdoc_endpoint.py` (필요 시)

- [ ] **Step 1: `test_revdoc_generator.py::_valid_md()` 헬퍼 수정**

`tests/test_revdoc_generator.py` 파일의 `_valid_md()` 함수에서 추적성 섹션 블록 교체:

**찾기**:
```python
        "## 추적성\n"
        "- Rule: R-001 고객 등급 산출\n"
        "- Condition: total_amount > 1000 AND tier = 'GOLD'\n"
        "- Evidence: customer_tier.py:45\n\n"
```

**교체**:
```python
        "## 추적성\n이 코드는 R-001 고객 등급 산출 업무 규칙을 구현하며, "
        "근거는 사내 정책 문서에서 확인할 수 있다.\n\n"
```

- [ ] **Step 2: `test_revdoc_generator.py`의 fail fixture 검토**

파일 내에서 `_invalid_md`, `_failing_md`, `invalid`, 또는 "Rule 누락"으로 fail 유도하는 패턴을 grep:

```bash
grep -nE "(_invalid_md|invalid_md|missing_rule|no_rule|without_rule)" tests/test_revdoc_generator.py
```

발견되는 각 헬퍼에 대해:
- **기존 동작**: "Rule/Condition/Evidence 삼각 중 하나 제거로 fail 유도"였다면 → **섹션 누락** 또는 **<500자**로 fail 유도하도록 변경
- **예상 패턴**:
  - 섹션 누락 버전: `_valid_md(length=900).replace("## 관련업무\n", "## XXX\n")`
  - 길이 부족 버전: `_valid_md(length=200)`

만약 grep 결과가 없으면 (전용 헬퍼 없이 인라인으로만 사용) 각 테스트 함수 내부에서 fail MD를 만드는 부분을 같은 원칙으로 수정.

- [ ] **Step 3: `test_revdoc_generator.py` 전체 실행**

```bash
python -m pytest tests/test_revdoc_generator.py -v
```
Expected: 모든 테스트 PASS. 실패 테스트가 있으면:
- "gate pass → refine 호출" 케이스가 pass 유지되는지
- "gate fail → retry" 케이스가 여전히 fail 상태를 만드는지 (섹션 누락 or <500자)
수동으로 해당 fixture 추가 조정.

- [ ] **Step 4: `test_revdoc_endpoint.py` fixture 검토**

```bash
grep -nE "(Rule:|Condition:|Evidence:|_valid_md|_invalid_md)" tests/test_revdoc_endpoint.py
```

발견되는 각 패턴에 대해 Step 1~2와 동일 원칙으로 수정. 엔드포인트 테스트는 주로 HTTP 응답 shape 검증이므로 MD 내용 변화가 테스트 통과에 영향 없을 수 있음 — 그 경우 변경 불필요.

- [ ] **Step 5: `test_revdoc_endpoint.py` 전체 실행**

```bash
python -m pytest tests/test_revdoc_endpoint.py -v
```
Expected: 모든 테스트 PASS.

- [ ] **Step 6: Commit**

```bash
git add tests/test_revdoc_generator.py tests/test_revdoc_endpoint.py
git commit -m "test(revdoc): update generator/endpoint fixtures for simplified gate"
```

---

## Task 7: 전체 테스트 스위트 + 실측 검증

**Files:**
- 코드 변경 없음 — 검증만.

- [ ] **Step 1: 전체 pytest 실행**

```bash
python -m pytest tests/ -v
```
Expected: 약 **273개** 테스트 PASS (269 기존 - 2 삭제 + 6 정규화/ensure_latest - 추가 2 seed_prompts). 실제 카운트는 출력 기준 확인.
- 실패 시: 관련 파일·라인 개별 디버그 → 수정 → 재실행 → 통과 후 commit.

- [ ] **Step 2: 서버 기동**

```bash
uvicorn app:app --port 8003 --reload
```
별도 터미널에서:
```bash
curl http://localhost:8003/health
```
Expected: `{"status":"ok"}`

- [ ] **Step 3: discount.pkb 실측 — 1-attempt pass 기대**

2026-04-23 테스트에서 3-attempts-fail했던 `discount.pkb`(샘플 경로는 로컬 테스트 데이터 디렉토리)로 `/reverse-doc` POST:

```bash
curl -X POST http://localhost:8003/reverse-doc \
  -H "X-Forge-Key: $FORGE_API_KEY" \
  -F "file=@C:/workspace/doc_root/samples/discount.pkb" \
  -o /tmp/discount_result.json
```

응답에서 `attempts` 필드 확인. Expected: `attempts: 1`, `gate.passed: true`.
불합격(attempts > 1)이면 생성된 MD 내용을 확인하여 섹션 누락·<500자 중 어느 것인지 진단 → 프롬프트 추가 튜닝 판단.

- [ ] **Step 4: 회귀 샘플 2건 — pass 유지 기대**

2026-04-23 라이브 테스트에서 `attempts=1 passed=true`였던 샘플 2건(로그/DB의 성공 케이스) 재호출:

```bash
for sample in SAMPLE1.pkb SAMPLE2.pkb; do
  curl -X POST http://localhost:8003/reverse-doc \
    -H "X-Forge-Key: $FORGE_API_KEY" \
    -F "file=@C:/workspace/doc_root/samples/$sample" \
    -o "/tmp/${sample}_result.json"
done
```

각 결과에서 `attempts: 1`, `gate.passed: true` 유지 확인. 실제 샘플 2건은 사용자가 2026-04-23 테스트 시 쓴 파일 중 선정.

- [ ] **Step 5: 수동 품질 체크**

Step 3, 4에서 생성된 각 MD를 육안으로 확인:
- 7개 섹션 각각에 **최소 1문단(2-3문장 이상)**의 의미 있는 서술 있는지
- "TBD", "추후 작성", "N/A" 같은 placeholder 없는지
- 섹션 제목만 있고 본문이 1줄 이하로 빈약한 경우 없는지

불합격 시: `revdoc/prompts/reverse_doc.md`의 `## 제약` 섹션에 "각 섹션 최소 2문단 권고" 등 튜닝 추가 → Task 3 Step 3~4 단계부터 재수정 → 재실측.
3회 반복해도 개선 안 되면: 스펙 §2.2(비목표의 품질 자동 게이트)를 재검토 — 별도 후속 작업으로 승격.

- [ ] **Step 6: 서버 종료**

```bash
# uvicorn 실행 중인 터미널에서 Ctrl+C
```

---

## Task 8: TODO.md + 메모리 업데이트 + 최종 commit

**Files:**
- Modify: `TODO.md`
- Modify: `CLAUDE.md` (참조 문서 목록에 새 스펙·플랜 추가)
- Create/Modify: `C:/Users/TPT848/.claude/projects/C--workspace-Forge/memory/project_revdoc_v2_tuning_backlog.md` (완료 처리)
- Modify: `C:/Users/TPT848/.claude/projects/C--workspace-Forge/memory/MEMORY.md` (완료 반영)

- [ ] **Step 1: TODO.md 업데이트**

`TODO.md`의 v3 섹션에 revdoc 단순화 완료 체크박스 추가. 예시:

```markdown
## v3 — revdoc 게이트 단순화 (완료 — 2026-04-24)

> 스펙: docs/superpowers/specs/2026-04-24-revdoc-gate-simplification-design.md
> 플랜: docs/superpowers/plans/2026-04-24-revdoc-gate-simplification.md

- [x] Task 1: `_normalize_prompt_text` 헬퍼
- [x] Task 2: `ensure_latest_prompt` 헬퍼 (기본 3 + 정규화 3 테스트)
- [x] Task 3: 프롬프트 rename + 내용 완화 + loader 경로
- [x] Task 4: `seed_prompts`를 `ensure_latest_prompt`로 전환
- [x] Task 5: `revdoc/gate.py` 단순화 (추적성 검사 제거)
- [x] Task 6: revdoc generator/endpoint fixture 재구성
- [x] Task 7: 전체 pytest + 실측 1-attempt pass 확인
- [x] Task 8: 문서·메모리 업데이트

핵심: 추적성 정규식 시늉 제거, 게이트는 "섹션 + 최소길이(500)"만 검사. 프롬프트는 자유 서술로 완화. 파일 변경이 startup에 DB로 자동 반영.
```

- [ ] **Step 2: CLAUDE.md 참조 문서 목록 업데이트**

`CLAUDE.md`의 "# 참조 문서" 테이블에 2줄 추가:

```markdown
| docs/superpowers/specs/2026-04-24-revdoc-gate-simplification-design.md | revdoc 게이트 단순화 스펙 |
| docs/superpowers/plans/2026-04-24-revdoc-gate-simplification.md | revdoc 게이트 단순화 구현 플랜 |
```

- [ ] **Step 3: 메모리 파일 `project_revdoc_v2_tuning_backlog.md` 완료 처리**

파일 끝에 다음 내용 append:

```markdown

**완료 (2026-04-24)**:
eng-review 결과 "5컬럼 추적성 테이블 강제"는 premature optimization으로 판정 → **단순화 방향 확정**.
실제 작업: 추적성 정규식 검사 통째로 제거, 프롬프트는 자유 서술로 완화. 게이트는 섹션(7개) + 최소길이(500) 2단계만 검사. `ensure_latest_prompt` 헬퍼 추가로 파일 변경이 startup에 자동 DB 반영.
273개 테스트 전부 통과, discount.pkb 1-attempt pass 실측 확인.

스펙: docs/superpowers/specs/2026-04-24-revdoc-gate-simplification-design.md
플랜: docs/superpowers/plans/2026-04-24-revdoc-gate-simplification.md
```

- [ ] **Step 4: `MEMORY.md` 인덱스 업데이트**

`C:/Users/TPT848/.claude/projects/C--workspace-Forge/memory/MEMORY.md`에서 revdoc v2 튜닝 항목의 설명 문구 업데이트:

**찾기**:
```markdown
- [revdoc v2 튜닝 — 프롬프트+Gate 재설계](project_revdoc_v2_tuning_backlog.md) — Gate false-positive + 추적 매트릭스(5컬럼 테이블) 도입. 2026-04-24 착수 예정
```

**교체**:
```markdown
- [revdoc 게이트 단순화 완료 (2026-04-24)](project_revdoc_v2_tuning_backlog.md) — 추적성 검사 제거 + 자유 서술로 완화. 고도화는 실사용 피드백 후로 보류
```

- [ ] **Step 5: 최종 commit**

```bash
git add TODO.md CLAUDE.md
git commit -m "docs(revdoc): record gate simplification completion in TODO + CLAUDE refs"
```

메모리 파일은 Forge 저장소 밖이라 별도 git 작업 불필요.

- [ ] **Step 6: 브랜치 상태 확인**

```bash
git log --oneline feature/v3-lightrag-extension ^main | head -20
git status
```
Expected:
- 신규 commit 7개 추가 (Task 1~6 + Task 8) — Task 7은 코드 변경 없어 commit 없음
- working tree clean

PR 머지는 별도 판단 (본 플랜 밖 — 스펙 §6 참조).

---

## Self-Review

**Spec coverage**:
- §4.1 게이트 단순화 → Task 5 ✓
- §4.2 프롬프트 파일 rename + 내용 완화 → Task 3 ✓
- §4.3.2 `_normalize_prompt_text` → Task 1 ✓
- §4.3.2 `ensure_latest_prompt` → Task 2 ✓
- §4.3.3 `seed_prompts` docstring + 경로 → Task 4 ✓
- §4.3.4 `_load_reverse_doc_prompt` 경로 → Task 3 Step 2 ✓
- §4.5 단일 워커 전제 → 스펙에 문서화됨, 플랜은 구현만 다룸 ✓
- §5.1 테스트 2개 삭제 → Task 5 Step 1 ✓
- §5.2 게이트 테스트 수정 → Task 5 Step 2~8 ✓
- §5.3 test_prompt_store.py 6건 추가 → Task 1 (3건) + Task 2 (3+3건) ✓
- §5.4 revdoc generator/endpoint fixture 재구성 → Task 6 ✓
- §5.5 실측 → Task 7 Step 3~5 ✓
- §5.6 정량 + 정성 기준 → Task 7 Step 1 + Step 5 ✓
- §6 롤아웃 → Task 7 + Task 8 ✓
- §9 추후 작업 (멀티워커 lock, 품질 자동게이트) → 플랜 범위 밖 (OK)

**Placeholder 스캔**: TBD/TODO/"implement later"/"add appropriate" 없음 ✓

**Type/symbol 일관성**:
- `_normalize_prompt_text(text: str) -> str` — Task 1 정의, Task 2에서 동일 시그니처로 호출 ✓
- `ensure_latest_prompt(store, prompt_type: str, current_text: str) -> None` — Task 2 정의, Task 4에서 동일 호출 ✓
- `seed_prompts(store) -> None` — 기존 시그니처 유지, Task 4에서 내부만 변경 ✓
- `_load_reverse_doc_prompt() -> str` — 기존 시그니처 유지, Task 3에서 내부 파일명만 변경 ✓
- `REQUIRED_SECTIONS` — Task 5에서 변경 없이 유지 ✓
- `GateVerdict(passed, details, reason, feedback)` — Task 5에서 필드 유지, `details` 내부 키만 변화 ✓
- `RevdocGate(min_length=500)` — Task 5에서 기본값만 800→500 변경 ✓

**테스트 카운트 재확인**: 269 기존 - 2 삭제 + 6 ensure_latest_prompt + 3 _normalize_prompt_text + 2 seed_prompts 회귀 = **278**. 스펙 §5.6의 "273" 추정치와 5개 차이. 원인: 플랜에 _normalize 테스트 3건과 seed_prompts 회귀 2건을 **추가**로 넣음(스펙 §5.3은 6건만 명시). 이 추가분은 eng-review의 §3.3(정규화 엣지) + §1.2(정규화 필요성) 강화 차원. 플랜 작성 시점에 발견한 디테일이므로 이게 맞음. 스펙 §5.6을 실구현 후 "약 278개"로 보정 가능. 완료 기준 위배 아님.

**빠진 항목 확인**: 없음.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-24-revdoc-gate-simplification.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
