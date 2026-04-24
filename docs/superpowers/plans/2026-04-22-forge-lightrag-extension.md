# Forge LightRAG Extension Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Docling extractor 통합, `/refine`·`/reverse-doc` 엔드포인트, LightRAG consumer 연계. C1 제약(Cortex 독립) 유지.

**Spec:** `docs/superpowers/specs/2026-04-22-forge-lightrag-extension-design.md`
**SRS:** `docs/SRS-v3-lightrag.md` (43 requirements)
**Review:** `docs/superpowers/reviews/2026-04-22-forge-lightrag-extension-review.md` ← **구현 전 필독** (CF-1~7, Q1~Q8 해결)

## Late Update — Docling-Serve 발견 (2026-04-22 저녁)

사용자가 VPS `/opt/docling/`에 **docling-serve 1.16.1** 별도 설치 + 테스트 완료. FastAPI + Swagger + APIKeyAuth + 멀티테넌트 지원.

→ **통합 전략을 옵션 A(라이브러리 import)에서 옵션 B(HTTP 호출)로 전환.**

| 영향 Task | 변경 |
|---|---|
| T11 | `pip install docling` 불필요, Dockerfile prewarm 불필요. 대신 `DOCLING_SERVE_URL`, `DOCLING_API_KEY` env 추가 |
| T12 | `from docling import ...` → `httpx.AsyncClient.post(f"{url}/v1/convert/file", files=...)`. 스펙: multipart/form-data, 동기+비동기 둘 다 지원 |
| T13 | DoclingLogStore → HTTP 호출 로그 (latency + status_code + error) |
| RES-02, RES-03 | Forge 이미지에 torch 안 들어감 (+2GB 절감) |
| COMP-02 | C1 준수 강화 — docling-serve는 완전 분리된 서비스 |

docling-serve 엔드포인트:
- `/health`, `/ready`, `/version`
- `POST /v1/convert/file` (multipart 동기)
- `POST /v1/convert/file/async` (multipart 비동기, TaskStatus 반환)
- `POST /v1/chunk/hybrid/source/async` (보너스: LightRAG 청킹과 중복 검토 대상)

**내일 재개 시**: 이 late update를 반영한 Plan revision(T11, T12, T13 교체) + ConvertDocumentsRequest/Response 스키마 확인 후 착수.

---

## Post-Review Updates (2026-04-22)

| 항목 | 반영 |
|---|---|
| CF-1 Callback payload 불일치 | T0에서 `CALLBACK_FIELD_MAP` env 추가 |
| CF-2 route 값 확장 | app.py Query pattern, models.py 주석 업데이트 |
| CF-3 source_code 전달 | Job 객체 동적 할당 (DB 저장 X) |
| CF-4 process_job 주입 | app.state에 refiner/revdoc_generator/stores 배치 |
| CF-5 InMemoryPromptStore | T7에 추가 (PG 없는 환경 대응) |
| CF-6 Docling prewarm | Volume mount + 배포 스크립트 (Dockerfile X) |
| CF-7 schema.sql | 변경 불필요 (신규 테이블만, ALTER 없음) |
| Q1~Q8 | 리뷰 문서 참조, Plan 각 Task에 반영 |

## 작업 위치 (🟢 로컬 / 🔵 VPS / 🟡 선택)

| Task | 위치 | Task | 위치 |
|---|---|---|---|
| T0 Preflight | 🟢 | T9 revdoc/generator | 🟢 |
| T1 RuleStore | 🟢🔵 | T10 `/reverse-doc` | 🟢 |
| T2 stages | 🟢 | T11 docling deps | 🟢🔵 |
| T3 validator | 🟢 | T12 docling_ex | 🟢 (로컬 실측 완료) |
| T4 Refiner | 🟢 | T13 DoclingLogStore | 🟢🔵 |
| T5 `/refine` | 🟢 | T14 router | 🟢 |
| T6 docs | 🟢 | T15 HWPX | 🟡🔵 |
| T7 PromptStore | 🟢🔵 | T16 regression | 🟢🔵 |
| T8 revdoc/gate | 🟢 | | |

**16 Task 중 12개 로컬 핵심 가능**, VPS는 PG 통합 + 배포만.

**Architecture:** 신규 `refine/`·`revdoc/`·`extractors/docling_ex.py`. 기존 Job / PromptStore / VLM 클라이언트 / Admin 패턴 100% 재사용. callback은 v2 그대로.

**Tech Stack:** Python 3.11+, FastAPI, docling ≥ 2.90, asyncpg, pytest

---

## Phase Dependency

```
Phase 1 (REFINE + CALLBACK)  ─┐
                              ├─→ Phase 2 (REVDOC, P1 Refiner 재사용)
Phase 3 (DOCLING + ROUTE) ────┘   병렬 가능

Phase 4 (SME 피드백) = 별도 SRS
```

**P1 ↔ P3 병렬 가능**. **P2는 P1 완료 후**.

---

## File Map

| 파일 | 역할 | Task |
|------|------|------|
| `schema.sql` | forge_refine_rules / forge_docling_logs / forge_prompts type 확장 | 1, 7, 11 |
| `job_store.py` | RefineRuleStore 추가 | 1 |
| `refine/stages/*.py` | 6단계 정제 | 2 |
| `refine/validator.py` | 검증 규칙 | 3 |
| `refine/__init__.py` | Refiner 파사드 | 4 |
| `app.py` | /refine, /reverse-doc 라우트 | 5, 10 |
| `models.py` | RefineRequest, ReverseDocRequest | 5, 10 |
| `docs/CORTEX-INTEGRATION.md` | LightRAG 예시 섹션 추가 | 6 |
| `revdoc/prompts/reverse_doc_v1.md` | 기본 프롬프트 시드 | 7 |
| `revdoc/gate.py` | 게이트 검증 | 8 |
| `revdoc/generator.py` | LLM 호출 + 재시도 | 9 |
| `requirements.txt` | docling 추가 | 11 |
| `Dockerfile` | docling 모델 prewarm | 11 |
| `extractors/docling_ex.py` | Docling extractor | 12 |
| `router.py` | docling 라우트 추가 | 14 |
| `extractors/office.py` | HWPX → Docling | 15 |
| `tests/` | 각 Task 단위 + integration | 전체 |

---

# Phase 0 — Preflight (공용 인프라)

## Task 0: env + lifespan wiring (CF-1, CF-4 통합)

**SRS:** CALLBACK-06 (신규), COMP-02
**Files:**
- Modify: `config.py`
- Modify: `app.py` (lifespan)
- Modify: `worker.py` (_send_callback rename)
- Modify: `.env.example`
- New: `tests/test_callback_field_map.py`

- [ ] **Step 1: config.py에 callback_field_map, callback_keep_unmapped 추가**

```python
class Config(BaseSettings):
    # ... 기존 필드
    callback_field_map: str | None = None  # JSON: {"content":"text","file_name":"file_source"}
    callback_keep_unmapped: bool = False
    revdoc_model: str | None = None  # None이면 vlm_model fallback
```

- [ ] **Step 2: worker.py `_send_callback` 직전에 필드 renaming**

```python
# worker.py 기존 payload 구성 직후
if config.callback_field_map:
    import json
    rename_map = json.loads(config.callback_field_map)
    new_payload = {rename_map.get(k, k): v for k, v in payload.items()}
    if not config.callback_keep_unmapped:
        new_payload = {k: v for k, v in new_payload.items() if k in rename_map.values()}
    payload = new_payload
```

- [ ] **Step 3: app.py lifespan에 신규 의존성 배치**

```python
# PG 분기
if config.database_url:
    # ... 기존
    from refine.rule_store import PostgresRefineRuleStore, InMemoryRefineRuleStore, seed_refine_rules
    a.state.refine_rule_store = PostgresRefineRuleStore(pool)
    await seed_refine_rules(a.state.refine_rule_store)
    # DoclingLogStore
    from job_store import PostgresDoclingLogStore
    a.state.docling_log_store = PostgresDoclingLogStore(pool)
else:
    from refine.rule_store import InMemoryRefineRuleStore, seed_refine_rules
    a.state.refine_rule_store = InMemoryRefineRuleStore()
    await seed_refine_rules(a.state.refine_rule_store)
    from job_store import InMemoryDoclingLogStore
    a.state.docling_log_store = InMemoryDoclingLogStore()

# 공통 (PG/InMemory 동일)
from refine import Refiner
a.state.refiner = await Refiner.from_store(a.state.refine_rule_store)

from revdoc.generator import ReverseDocGenerator
a.state.revdoc_generator = ReverseDocGenerator(
    vlm=VLMClient(config),
    prompt_store=a.state.prompt_store if hasattr(a.state, 'prompt_store') else None,
    refiner=a.state.refiner,
)
```

- [ ] **Step 4: process_job 시그니처 확장**

```python
async def process_job(
    job: Job, file_bytes: bytes, route: str, store: JobStore, config: Config, *,
    meta_extractor=None, vlm_log_store=None, prompts=None,
    refiner=None, revdoc_generator=None, docling_log_store=None,
) -> None:
```

- [ ] **Step 5: `_safe_process` wrapper 업데이트 (app.py)**

기존 signature에 신규 3개 파라미터 추가 + `asyncio.create_task` 호출부 업데이트.

- [ ] **Step 6: app.py `/convert` Query pattern 확장 (CF-2)**

```python
route: str | None = Query(None, pattern="^(extract|vlm|docling)$", ...)
```

- [ ] **Step 7: models.py `ConvertResult.route` 주석 업데이트 (CF-2)**

```python
route: str  # "vlm" | "extract" | "docling" | "reverse_doc" | "refine"
```

- [ ] **Step 8: 테스트 (CALLBACK_FIELD_MAP)**

```python
@pytest.mark.asyncio
async def test_callback_renames_fields_for_lightrag(httpx_mock):
    config = Config(callback_field_map='{"content":"text","file_name":"file_source"}',
                    callback_keep_unmapped=False)
    # mock callback_url 서버
    # Forge 내부 payload → rename → POST
    # 어설트: LightRAG가 기대하는 {"text": ..., "file_source": ...}만 포함

@pytest.mark.asyncio
async def test_callback_keeps_original_without_map():
    config = Config(callback_field_map=None)
    # 기존 Cortex 호환 payload 그대로
```

- [ ] **Step 9: `.env.example` 주석 추가**

```
# Generic callback field rename (consumer-agnostic)
# Example for LightRAG: {"content":"text","file_name":"file_source"}
CALLBACK_FIELD_MAP=
CALLBACK_KEEP_UNMAPPED=false

# REVDOC dedicated model (None이면 VLM_MODEL 공용)
REVDOC_MODEL=
```

---

# Phase 1 — REFINE + CALLBACK

## Task 1: forge_refine_rules 테이블 + RefineRuleStore

**SRS:** REFINE-06
**Files:**
- Modify: `schema.sql`
- Modify: `job_store.py`
- New: `tests/test_refine_rule_store.py`

- [ ] **Step 1: schema.sql에 forge_refine_rules 추가**

```sql
CREATE TABLE IF NOT EXISTS forge_refine_rules (
    id          SERIAL PRIMARY KEY,
    stage       VARCHAR(30) NOT NULL,  -- encoding/newline/special_char/frontmatter/codefence/traceability/validator
    version     INT NOT NULL,
    config      JSONB NOT NULL,
    is_active   BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_forge_refine_rules_active
    ON forge_refine_rules(stage) WHERE is_active = TRUE;
```

- [ ] **Step 2: RefineRuleStore 클래스 (PromptStore 패턴)**

`job_store.py`에 추가:

```python
class RefineRuleStore(ABC):
    @abstractmethod
    async def active(self, stage: str) -> dict: ...
    @abstractmethod
    async def upsert(self, stage: str, config: dict) -> int: ...
    @abstractmethod
    async def list_versions(self, stage: str) -> list[dict]: ...

class InMemoryRefineRuleStore(RefineRuleStore):
    def __init__(self):
        self._rules = {}  # stage -> (version, config)
    # ...

class PostgresRefineRuleStore(RefineRuleStore):
    def __init__(self, pool):
        self.pool = pool
    # forge_refine_rules 테이블 쿼리
```

- [ ] **Step 3: 기본 시드 (각 stage 버전 1 기본값)**

`job_store.py`에 `seed_refine_rules()` 추가. Stage별 기본 config:

```python
DEFAULTS = {
    "encoding": {"try_order": ["utf-8", "utf-8-sig", "cp949", "euc-kr"]},
    "newline": {"patterns": [r"\\n", r"\\r\\n"], "replace_with": "\n"},
    "special_char": {"map": {"~": "∼", "·": "·"}, "normalize_width": True},
    "frontmatter": {"delimiters": ["---", "+++"], "keep_keys": []},
    "codefence": {"strip": False, "keep_lang": True},
    "traceability": {"pattern": r"(\w+)\s*↔\s*(\w+)", "replace": r"\1은 \2에 연결된다."},
    "validator": {
        "require_utf8": True,
        "min_newlines": 1,
        "min_korean_ratio": 0.1,
        "min_length": 100,
    },
}
```

- [ ] **Step 4: 테스트 작성**

```python
# tests/test_refine_rule_store.py
@pytest.mark.asyncio
async def test_seed_and_active():
    store = InMemoryRefineRuleStore()
    await seed_refine_rules(store)
    r = await store.active("encoding")
    assert "try_order" in r
    assert r["try_order"][0] == "utf-8"

@pytest.mark.asyncio
async def test_upsert_increments_version():
    store = InMemoryRefineRuleStore()
    v1 = await store.upsert("newline", {"patterns": [r"\\n"], "replace_with": "\n"})
    v2 = await store.upsert("newline", {"patterns": [r"\\n", r"\\r"], "replace_with": "\n"})
    assert v2 == v1 + 1
```

---

## Task 2: refine/stages/* — 6단계 구현

**SRS:** REFINE-02
**Files:**
- New: `refine/__init__.py`
- New: `refine/stages/__init__.py`
- New: `refine/stages/encoding.py`
- New: `refine/stages/newline.py`
- New: `refine/stages/special_char.py`
- New: `refine/stages/frontmatter.py`
- New: `refine/stages/codefence.py`
- New: `refine/stages/traceability.py`
- New: `tests/test_refine_stages.py`

- [ ] **Step 1: 공통 인터페이스 정의**

`refine/stages/__init__.py`:

```python
from dataclasses import dataclass
from typing import Protocol

@dataclass
class StageReport:
    stage: str
    applied: bool
    changes: int
    details: dict

class Stage(Protocol):
    def apply(self, text: str | bytes) -> tuple[str, StageReport]: ...
```

- [ ] **Step 2: encoding.py**

```python
class EncodingStage:
    def __init__(self, config: dict):
        self.try_order = config["try_order"]

    def apply(self, raw: bytes | str) -> tuple[str, StageReport]:
        if isinstance(raw, str):
            return raw, StageReport("encoding", False, 0, {"reason": "already str"})
        for enc in self.try_order:
            try:
                text = raw.decode(enc)
                return text, StageReport("encoding", True, 0, {"from": enc})
            except UnicodeDecodeError:
                continue
        raise ValueError(f"decode failed (tried {self.try_order})")
```

- [ ] **Step 3: newline.py**

```python
class NewlineStage:
    def __init__(self, config: dict):
        self.patterns = [re.compile(p) for p in config["patterns"]]
        self.replace_with = config["replace_with"]

    def apply(self, text: str) -> tuple[str, StageReport]:
        count = 0
        for p in self.patterns:
            text, n = p.subn(self.replace_with, text)
            count += n
        return text, StageReport("newline", count > 0, count, {})
```

- [ ] **Step 4: special_char.py**

```python
import unicodedata

class SpecialCharStage:
    def __init__(self, config: dict):
        self.mapping = config.get("map", {})
        self.normalize_width = config.get("normalize_width", False)

    def apply(self, text: str) -> tuple[str, StageReport]:
        replacements = 0
        for src, dst in self.mapping.items():
            text_new = text.replace(src, dst)
            replacements += (len(text) - len(text_new.replace(dst, src))) // max(len(src), 1)
            text = text_new
        if self.normalize_width:
            text = unicodedata.normalize("NFKC", text)
        return text, StageReport("special_char", replacements > 0, replacements, {})
```

- [ ] **Step 5: frontmatter.py**

```python
class FrontmatterStage:
    def __init__(self, config: dict):
        self.delimiters = config.get("delimiters", ["---"])
        self.keep_keys = set(config.get("keep_keys", []))

    def apply(self, text: str) -> tuple[str, StageReport]:
        # 첫 줄이 delimiter로 시작하면 다음 delimiter까지 제거
        # keep_keys에 있는 키는 주석으로 남김 (선택)
        for d in self.delimiters:
            if text.lstrip().startswith(d):
                end = text.find(f"\n{d}", len(d))
                if end > 0:
                    stripped = text[end + len(d) + 1:].lstrip("\n")
                    return stripped, StageReport("frontmatter", True,
                        text[:end].count("\n"), {"delimiter": d})
        return text, StageReport("frontmatter", False, 0, {})
```

- [ ] **Step 6: codefence.py**

```python
class CodefenceStage:
    def __init__(self, config: dict):
        self.strip = config.get("strip", False)

    def apply(self, text: str) -> tuple[str, StageReport]:
        if not self.strip:
            return text, StageReport("codefence", False, 0, {"reason": "strip=false"})
        # ```lang ... ``` 블록 제거
        pattern = re.compile(r"```.*?\n.*?```", re.DOTALL)
        new_text, n = pattern.subn("", text)
        return new_text, StageReport("codefence", n > 0, n, {})
```

- [ ] **Step 7: traceability.py**

```python
class TraceabilityStage:
    def __init__(self, config: dict):
        self.pattern = re.compile(config["pattern"])
        self.replace = config["replace"]

    def apply(self, text: str) -> tuple[str, StageReport]:
        new_text, n = self.pattern.subn(self.replace, text)
        return new_text, StageReport("traceability", n > 0, n, {})
```

- [ ] **Step 8: 테스트 (stage별 unit)**

각 stage마다 최소 3개 케이스 (적용 성공 / 적용 대상 없음 / 엣지 케이스).

```python
def test_encoding_cp949_to_utf8():
    stage = EncodingStage({"try_order": ["utf-8", "cp949"]})
    raw = "한글".encode("cp949")
    text, report = stage.apply(raw)
    assert text == "한글"
    assert report.details["from"] == "cp949"

def test_newline_literal_to_real():
    stage = NewlineStage({"patterns": [r"\\n"], "replace_with": "\n"})
    text, report = stage.apply("a\\nb\\nc")
    assert text == "a\nb\nc"
    assert report.changes == 2
```

---

## Task 3: refine/validator.py

**SRS:** REFINE-04
**Files:**
- New: `refine/validator.py`
- New: `tests/test_refine_validator.py`

- [ ] **Step 1: Validator 구현**

```python
from dataclasses import dataclass

@dataclass
class GateVerdict:
    passed: bool
    checks: dict
    reason: str | None = None

class Validator:
    def __init__(self, config: dict):
        self.config = config

    def check(self, text: str) -> GateVerdict:
        checks = {}
        c = self.config

        # UTF-8 (이미 str이면 통과)
        checks["utf8"] = True

        # 개행 수
        newlines = text.count("\n")
        checks["newlines"] = newlines

        # 한글 비율
        hangul = sum(1 for ch in text if 0xAC00 <= ord(ch) <= 0xD7A3)
        total = len(text) or 1
        korean_ratio = hangul / total
        checks["korean_ratio"] = round(korean_ratio, 3)

        # 길이
        checks["length"] = len(text)

        # 판정
        if newlines < c["min_newlines"]:
            return GateVerdict(False, checks, f"newlines {newlines} < min {c['min_newlines']}")
        if korean_ratio < c["min_korean_ratio"]:
            return GateVerdict(False, checks, f"korean_ratio {korean_ratio:.2f} < min {c['min_korean_ratio']}")
        if len(text) < c["min_length"]:
            return GateVerdict(False, checks, f"length {len(text)} < min {c['min_length']}")
        return GateVerdict(True, checks)
```

- [ ] **Step 2: 테스트 (경계값)**

```python
def test_pass_all_thresholds():
    v = Validator({"require_utf8": True, "min_newlines": 1, "min_korean_ratio": 0.1, "min_length": 100})
    text = "한글 내용.\n" * 20  # 충분
    assert v.check(text).passed

def test_fail_korean_ratio_below_threshold():
    v = Validator({"require_utf8": True, "min_newlines": 1, "min_korean_ratio": 0.1, "min_length": 100})
    text = "English only text " * 20 + "\n"
    verdict = v.check(text)
    assert not verdict.passed
    assert "korean_ratio" in verdict.reason
```

---

## Task 4: refine/ 파사드 (Refiner)

**SRS:** REFINE-02,03,05
**Files:**
- Modify: `refine/__init__.py`
- New: `tests/test_refiner.py`

- [ ] **Step 1: Refiner 파사드**

```python
from .stages.encoding import EncodingStage
from .stages.newline import NewlineStage
from .stages.special_char import SpecialCharStage
from .stages.frontmatter import FrontmatterStage
from .stages.codefence import CodefenceStage
from .stages.traceability import TraceabilityStage
from .validator import Validator

@dataclass
class RefineResult:
    text: str
    report: dict   # {stage_name: StageReport.__dict__}
    quality: dict  # {gate: 'pass'|'fail', checks: {...}, reason?}
    rule_versions: dict

class Refiner:
    @classmethod
    async def from_store(cls, store: RefineRuleStore) -> "Refiner":
        # 모든 stage active config 로드
        configs = {}
        for stage in ("encoding", "newline", "special_char", "frontmatter", "codefence", "traceability", "validator"):
            configs[stage] = await store.active(stage)
        return cls(configs)

    def __init__(self, configs: dict):
        self.stages = [
            EncodingStage(configs["encoding"]),
            NewlineStage(configs["newline"]),
            SpecialCharStage(configs["special_char"]),
            FrontmatterStage(configs["frontmatter"]),
            CodefenceStage(configs["codefence"]),
            TraceabilityStage(configs["traceability"]),
        ]
        self.validator = Validator(configs["validator"])
        self.rule_versions = {k: v.get("version", 1) for k, v in configs.items()}

    def refine(self, raw: bytes | str) -> RefineResult:
        text = raw
        report = {}
        for stage in self.stages:
            text, sr = stage.apply(text)
            report[sr.stage] = sr.__dict__
        verdict = self.validator.check(text)
        return RefineResult(
            text=text,
            report=report,
            quality={"gate": "pass" if verdict.passed else "fail",
                     "checks": verdict.checks,
                     "reason": verdict.reason},
            rule_versions=self.rule_versions,
        )
```

- [ ] **Step 2: 통합 테스트 (6단계 전체)**

```python
@pytest.mark.asyncio
async def test_full_refine_cp949_with_literal_newlines():
    store = InMemoryRefineRuleStore()
    await seed_refine_rules(store)
    refiner = await Refiner.from_store(store)

    raw = "---\ntitle: test\n---\n한글 본문입니다.\\n두번째 줄.".encode("cp949")
    r = refiner.refine(raw)
    assert "title:" not in r.text
    assert "\n두번째" in r.text
    assert r.quality["gate"] == "pass"
```

---

## Task 5: POST /refine 엔드포인트

**SRS:** REFINE-01,05,07
**Files:**
- Modify: `models.py`
- Modify: `app.py`
- New: `tests/test_refine_endpoint.py`

- [ ] **Step 1: models.py에 RefineResponse 추가**

```python
class RefineResponse(BaseModel):
    refined_text: str
    report: dict
    quality: dict
    rule_versions: dict
```

- [ ] **Step 2: app.py에 라우트 추가**

```python
@app.post("/refine", response_model=RefineResponse)
async def refine_sync(
    file: UploadFile | None = File(None),
    text: str | None = Form(None),
):
    """동기 정제. 1MB 이하 MD 권장."""
    if file is None and text is None:
        raise HTTPException(400, "file or text required")
    raw = await file.read() if file else text
    refiner = await get_refiner()  # DI from app.state
    result = refiner.refine(raw)
    return RefineResponse(
        refined_text=result.text,
        report=result.report,
        quality=result.quality,
        rule_versions=result.rule_versions,
    )

@app.post("/refine/async")
async def refine_async(background_tasks: BackgroundTasks, ...):
    """비동기. 큰 MD용. Job 생성 후 job_id 반환."""
    # 기존 /convert 패턴 그대로
```

- [ ] **Step 3: 테스트**

```python
def test_refine_sync_success():
    response = client.post("/refine", data={"text": "한글 본문.\n두번째 줄."})
    assert response.status_code == 200
    assert response.json()["quality"]["gate"] in ("pass", "fail")
```

---

## Task 6: docs/CORTEX-INTEGRATION.md 확장

**SRS:** CALLBACK-05
**Files:**
- Modify: `docs/CORTEX-INTEGRATION.md`

- [ ] **Step 1: "Consumer 예시 — LightRAG" 섹션 추가**

(C1 준수: "LightRAG 전용 지원" 표현 금지. consumer 예시로만)

```markdown
## Consumer 예시

### Cortex (기존)
```bash
curl -X POST ".../convert?callback_url=http://cortex:9000/v1/ingest" -F "file=@doc.pdf"
```

### LightRAG (예시)
```bash
curl -X POST ".../convert?callback_url=http://lightrag:9621/documents/upload" -F "file=@doc.pdf"
```

동일 callback 스펙. consumer 측에서 `pre_converted=true`, `X-API-Key` 헤더를 수용하면 됨.
```

---

# Phase 2 — REVDOC

## Task 7: forge_prompts에 reverse_doc 시드

**SRS:** REVDOC-02,03
**Files:**
- New: `revdoc/prompts/reverse_doc_v1.md`
- Modify: `job_store.py` (seed)
- Modify: `schema.sql` (코멘트만, type 제약 없음)

- [ ] **Step 1: 프롬프트 시드 파일 작성**

`revdoc/prompts/reverse_doc_v1.md`를 day1-plsql-parsing의 `prompt_A_doc_gen.md`에서 이식. 필수 7섹션:

```markdown
# 역문서 생성 프롬프트 v1

## 역할
당신은 경험 많은 시니어 개발자이자 도메인 전문가다. 아래 PL/SQL 코드를 읽고 업무 규칙 문서를 생성하라.

## 출력 형식 (필수 7섹션, 헤딩 정확히 사용)
## 업무목적
## 처리흐름
## 입력/출력
## 규칙/예외
## 근거
## 추적성
## 관련업무

## 제약
- 추적성은 Rule/Condition/Evidence 삼각으로 최소 1건 명시
- 출력은 Markdown
- 섹션 헤더 순서 변경 금지
...
```

- [ ] **Step 2: seed_prompts()에 reverse_doc 추가**

```python
async def seed_prompts(store: PromptStore):
    # 기존 semantic/meta_extract 시드 뒤에
    with open("revdoc/prompts/reverse_doc_v1.md", encoding="utf-8") as f:
        reverse_doc = f.read()
    await store.upsert(type="reverse_doc", text=reverse_doc)
```

---

## Task 8: revdoc/gate.py

**SRS:** REVDOC-05
**Files:**
- New: `revdoc/__init__.py`
- New: `revdoc/gate.py`
- New: `tests/test_revdoc_gate.py`

- [ ] **Step 1: 게이트 검증 구현**

```python
import re
from dataclasses import dataclass

REQUIRED_SECTIONS = ["업무목적", "처리흐름", "입력/출력", "규칙/예외", "근거", "추적성", "관련업무"]

@dataclass
class GateVerdict:
    passed: bool
    details: dict
    reason: str | None = None
    feedback: str | None = None  # 실패 시 재시도 프롬프트 힌트

class RevdocGate:
    def __init__(self, min_length: int = 800):
        self.min_length = min_length

    def check(self, md: str) -> GateVerdict:
        details = {}

        # 1. 섹션 7개
        missing = []
        for section in REQUIRED_SECTIONS:
            if not re.search(rf"^##+\s*{re.escape(section)}", md, re.M):
                missing.append(section)
        details["missing_sections"] = missing
        if missing:
            return GateVerdict(False, details,
                f"sections missing: {missing}",
                f"출력에 다음 섹션이 누락됨: {missing}. 정확한 헤더로 다시 생성하라.")

        # 2. Traceability 삼각
        has_rule = bool(re.search(r"Rule\s*[:：]", md))
        has_cond = bool(re.search(r"Condition\s*[:：]", md))
        has_evid = bool(re.search(r"Evidence\s*[:：]", md))
        details["traceability"] = {"rule": has_rule, "condition": has_cond, "evidence": has_evid}
        if not (has_rule and has_cond and has_evid):
            return GateVerdict(False, details,
                "traceability 삼각 미충족",
                "추적성 섹션에 Rule/Condition/Evidence 세 항목을 모두 포함하라.")

        # 3. 길이
        details["length"] = len(md)
        if len(md) < self.min_length:
            return GateVerdict(False, details,
                f"length {len(md)} < {self.min_length}",
                f"본문이 짧다 ({len(md)}자). 각 섹션을 충분히 서술하라.")

        return GateVerdict(True, details)
```

- [ ] **Step 2: 테스트**

```python
def test_gate_pass_minimal():
    gate = RevdocGate(min_length=100)
    md = "## 업무목적\na\n## 처리흐름\nb\n## 입력/출력\nc\n## 규칙/예외\nd\n## 근거\nRule: R1\nCondition: C1\nEvidence: E1\n## 추적성\nx\n## 관련업무\ny\n" + "z"*100
    verdict = gate.check(md)
    assert verdict.passed

def test_gate_fail_missing_section():
    gate = RevdocGate(min_length=10)
    md = "## 업무목적\n\n## 처리흐름\n"
    verdict = gate.check(md)
    assert not verdict.passed
    assert "missing" in verdict.reason
```

---

## Task 9: revdoc/generator.py

**SRS:** REVDOC-01,04,06,08
**Files:**
- New: `revdoc/generator.py`
- New: `tests/test_revdoc_generator.py`

- [ ] **Step 1: Generator 구현 (LLM 호출 + 재시도 + Refine 자동)**

```python
from vlm import VLMClient  # 기존
from refine import Refiner
from .gate import RevdocGate, GateVerdict

class ReverseDocGenerator:
    def __init__(self, vlm: VLMClient, prompt_store, refiner: Refiner,
                 gate: RevdocGate = None, max_retries: int = 2):
        self.vlm = vlm
        self.prompt_store = prompt_store
        self.refiner = refiner
        self.gate = gate or RevdocGate()
        self.max_retries = max_retries

    async def generate(self, source_code: str, file_name: str) -> dict:
        """리턴: {result_text, prompt_version, gate, refine_report, attempts}"""
        prompt_row = await self.prompt_store.active("reverse_doc")
        base_prompt = prompt_row["text"]
        prompt_version = f"reverse_doc-v{prompt_row['version']}"

        feedback = None
        attempts = 0
        for i in range(self.max_retries + 1):
            attempts += 1
            full_prompt = base_prompt
            if feedback:
                full_prompt += f"\n\n## 재시도 피드백\n{feedback}"

            # VLM 클라이언트 재사용 (S1 Semaphore, S2 retry 자동)
            generated = await self.vlm.process_text(
                text=source_code,
                prompt=full_prompt,
                purpose="reverse_doc",
            )

            verdict = self.gate.check(generated)
            if verdict.passed:
                # 자동 refine (HTTP 아니고 직접 호출)
                refined = self.refiner.refine(generated)
                return {
                    "result_text": refined.text,
                    "prompt_version": prompt_version,
                    "gate": {"passed": True, "details": verdict.details},
                    "refine_report": refined.report,
                    "attempts": attempts,
                }
            feedback = verdict.feedback

        # 재시도 소진
        return {
            "result_text": generated,
            "prompt_version": prompt_version,
            "gate": {"passed": False, "details": verdict.details, "reason": verdict.reason},
            "refine_report": None,
            "attempts": attempts,
        }
```

- [ ] **Step 2: vlm.py에 process_text 메서드 추가 (Vision 아닌 텍스트 LLM용)**

```python
# vlm.py에 추가
async def process_text(self, text: str, prompt: str, purpose: str) -> str:
    """Vision 없이 텍스트만 LLM 호출. Semaphore + retry 동일 적용."""
    async with self._semaphore:
        return await self._call_with_retry(
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": text},
            ],
            purpose=purpose,
        )
```

- [ ] **Step 3: 테스트 (LLM mock)**

```python
@pytest.mark.asyncio
async def test_generator_pass_first_try(mocker):
    vlm = mocker.AsyncMock()
    vlm.process_text = mocker.AsyncMock(return_value=VALID_7_SECTION_MD)
    store = make_mock_prompt_store(reverse_doc_text="...")
    refiner = make_refiner_inmemory()
    gen = ReverseDocGenerator(vlm, store, refiner)
    result = await gen.generate("CREATE PROCEDURE foo ...", "foo.pkb")
    assert result["gate"]["passed"]
    assert result["attempts"] == 1

@pytest.mark.asyncio
async def test_generator_retries_on_gate_fail(mocker):
    vlm = mocker.AsyncMock()
    vlm.process_text = mocker.AsyncMock(side_effect=[INVALID_MD, INVALID_MD, VALID_MD])
    # ...
    assert result["attempts"] == 3
```

---

## Task 10: POST /reverse-doc 엔드포인트

**SRS:** REVDOC-01,07
**Files:**
- Modify: `models.py`
- Modify: `app.py`
- Modify: `worker.py`
- New: `tests/test_revdoc_endpoint.py`

- [ ] **Step 1: models.py에 ReverseDocJob 필드**

기존 Job에 source_format='reverse_doc' 허용. 별도 모델 불필요.

- [ ] **Step 2: app.py에 라우트**

```python
@app.post("/reverse-doc")
async def reverse_doc(
    file: UploadFile = File(...),
    callback_url: str | None = Form(None),
    requested_by: str | None = Form(None),
):
    raw = await file.read()
    if len(raw) > 200 * 1024:
        raise HTTPException(413, "max 200KB")
    # Job 생성 (source_format='reverse_doc', route='reverse_doc')
    job = await store.create(
        file_name=file.filename,
        source_format="reverse_doc",
        route="reverse_doc",
        callback_url=callback_url,
        requested_by=requested_by,
        source_code=raw.decode("utf-8", errors="replace"),
    )
    # worker에 dispatch
    asyncio.create_task(_safe_process(job.id, raw, file.filename))
    return {"job_id": str(job.id), "status": "queued"}
```

- [ ] **Step 3: worker.py에 reverse_doc 분기**

```python
# worker.py _process() 내
elif job.route == "reverse_doc":
    generator = get_revdoc_generator()
    result = await generator.generate(job.source_code, job.file_name)
    await store.complete(
        job.id,
        result_text=result["result_text"],
        quality={"gate": result["gate"], "refine_report": result["refine_report"], "attempts": result["attempts"]},
        prompt_version=result["prompt_version"],
    )
    if job.callback_url:
        await _send_callback(job.callback_url, job)
```

- [ ] **Step 4: 엔드포인트 테스트**

---

# Phase 3 — DOCLING + ROUTE + HWPX

## Task 11: docling 의존성 + schema + Dockerfile

**SRS:** DOCLING-01,03,08; RES-02,03
**Files:**
- Modify: `requirements.txt`
- Modify: `schema.sql`
- Modify: `Dockerfile`

- [ ] **Step 1: requirements.txt**

```
docling>=2.90.0
```

- [ ] **Step 2: schema.sql**

```sql
CREATE TABLE IF NOT EXISTS forge_docling_logs (
    id              SERIAL PRIMARY KEY,
    job_id          UUID REFERENCES forge_jobs(id),
    pages           INT,
    latency_ms      INT,
    fallback        BOOLEAN DEFAULT FALSE,
    fallback_reason TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_forge_docling_logs_job ON forge_docling_logs(job_id);
```

- [ ] **Step 3: Dockerfile 모델 prewarm (이미지 빌드 시 1회 다운로드)**

```dockerfile
# 기존 CMD 앞에 추가
RUN python -c "from docling.document_converter import DocumentConverter; DocumentConverter()" \
    2>&1 | tail -5
# 이로써 ~506MB HF 캐시가 이미지에 포함 (RES-02 ≤1GB 준수)
```

주의: 캐시 위치 `/root/.cache/huggingface`. 런타임 볼륨 마운트 시 덮어쓰지 않도록 문서화.

---

## Task 12: extractors/docling_ex.py

**SRS:** DOCLING-01~08
**Files:**
- New: `extractors/docling_ex.py`
- Modify: `extractors/__init__.py` (register)
- New: `tests/test_docling_extractor.py`
- New: `tests/fixtures/bok_fsr_p1-10.pdf` (한국은행 10p)
- New: `tests/fixtures/attention_short.pdf` (arXiv 3p)

- [ ] **Step 1: docling_ex.py 구현**

```python
import asyncio, time, tempfile, os
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from models import ConvertResult, Quality
from logger import logger

_CONVERTER = None
_SEMAPHORE = None

def _get_converter():
    global _CONVERTER
    if _CONVERTER is None:
        opts = PdfPipelineOptions()
        opts.accelerator_options.device = "cpu"
        _CONVERTER = DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
        )
    return _CONVERTER

def _get_semaphore(concurrency: int):
    global _SEMAPHORE
    if _SEMAPHORE is None:
        _SEMAPHORE = asyncio.Semaphore(concurrency)
    return _SEMAPHORE

def _convert_sync(file_bytes: bytes, suffix: str) -> tuple[str, int]:
    """DocumentConverter는 파일 경로 요구 → tempfile."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
        f.write(file_bytes)
        tmp_path = f.name
    try:
        result = _get_converter().convert(tmp_path)
        md = result.document.export_to_markdown()
        pages = len(result.document.pages)
        return md, pages
    finally:
        os.unlink(tmp_path)

async def extract(file_bytes: bytes, file_name: str, concurrency: int = 3) -> ConvertResult:
    suffix = os.path.splitext(file_name)[1] or ".pdf"
    sem = _get_semaphore(concurrency)
    t0 = time.time()
    try:
        async with sem:
            md, pages = await asyncio.to_thread(_convert_sync, file_bytes, suffix)
        latency_ms = int((time.time() - t0) * 1000)
        await _log_docling(pages=pages, latency_ms=latency_ms, fallback=False)
        return ConvertResult(
            text=md,
            format="md",
            pages=pages,
            file_name=file_name,
            source_format=suffix.lstrip("."),
            route="docling",
            quality=Quality(
                total_chars=len(md),
                chars_per_page=len(md) // max(pages, 1),
                total_pages=pages,
                failed_pages=0,
                confidence="high",
                method="docling",
            ),
        )
    except (MemoryError, RuntimeError, Exception) as e:
        logger.warning(f"Docling failed ({type(e).__name__}: {e}), falling back to pypdfium2")
        await _log_docling(pages=0, latency_ms=int((time.time()-t0)*1000),
                           fallback=True, reason=f"{type(e).__name__}: {e}")
        from extractors.pdf import extract as pdf_fallback
        result = await pdf_fallback(file_bytes, file_name)
        # quality에 fallback 마킹
        result.quality.method = "pypdfium2_fallback"
        return result

async def _log_docling(pages: int, latency_ms: int, fallback: bool, reason: str = None):
    # PostgresDoclingLogStore.insert(...) 또는 InMemory
    ...
```

- [ ] **Step 2: tests 추가 + fixtures 복사**

```bash
# 개발 환경에서 1회
cp /c/workspace/docling-test/bok_fsr_p1-10.pdf tests/fixtures/
```

```python
@pytest.mark.asyncio
async def test_docling_korean_pdf_preserves_tables():
    with open("tests/fixtures/bok_fsr_p1-10.pdf", "rb") as f:
        data = f.read()
    result = await extract(data, "bok.pdf")
    # 표 구조 보존 확인
    assert "| 1. 가계 및 기업 신용" in result.text
    assert "| 전체" in result.text
    # 섹션 헤딩
    assert "## (1) 가계신용" in result.text

@pytest.mark.asyncio
async def test_docling_oom_falls_back_to_pypdfium2(mocker):
    mocker.patch("extractors.docling_ex._convert_sync", side_effect=MemoryError("mock"))
    with open("tests/fixtures/attention_short.pdf", "rb") as f:
        result = await extract(f.read(), "a.pdf")
    assert result.quality.method == "pypdfium2_fallback"
```

---

## Task 13: forge_docling_logs Store

**SRS:** DOCLING-08
**Files:**
- Modify: `job_store.py`

- [ ] **Step 1: DoclingLogStore 추가 (VLMLogStore 패턴)**

```python
class DoclingLogStore(ABC):
    @abstractmethod
    async def insert(self, job_id, pages, latency_ms, fallback, reason): ...

class InMemoryDoclingLogStore(DoclingLogStore):
    def __init__(self):
        self._rows = []
    async def insert(self, **kw):
        self._rows.append({**kw, "created_at": datetime.utcnow()})

class PostgresDoclingLogStore(DoclingLogStore):
    # forge_docling_logs 테이블 insert
```

---

## Task 14: router.py 확장

**SRS:** ROUTE-06~09
**Files:**
- Modify: `router.py`
- Modify: `tests/test_router.py`

- [ ] **Step 1: docling 라우트 추가**

```python
# 기존 PDF 판정:
# if chars_per_mb < VLM_THRESHOLD: return "vlm"
# else: return "extract"

# 변경:
def route_for(source_format: str, chars_per_mb: float,
              route_override: str | None = None) -> str:
    if route_override in ("vlm", "extract", "docling"):
        return route_override
    if source_format == "pdf":
        if chars_per_mb < VLM_THRESHOLD:
            return "vlm"
        return "docling"  # 기본 변경 (기존: extract)
    if source_format == "hwpx":
        return "docling"  # via office.py
    if source_format in ("docx", "pptx", "xlsx"):
        return "extract"
    # ...
```

- [ ] **Step 2: 테스트 업데이트 (기존 ROUTE-04 회귀 체크)**

```python
def test_pdf_with_text_routes_to_docling_by_default():
    assert route_for("pdf", chars_per_mb=500) == "docling"

def test_pdf_override_extract_still_works():
    assert route_for("pdf", chars_per_mb=500, route_override="extract") == "extract"

def test_pdf_scan_still_routes_to_vlm():
    assert route_for("pdf", chars_per_mb=50) == "vlm"
```

---

## Task 15: HWPX → Docling 경로

**SRS:** ROUTE-09
**Files:**
- Modify: `extractors/office.py`
- Modify: `worker.py`
- Modify: `tests/test_hwpx.py`

- [ ] **Step 1: office.py에서 HWPX → DOCX 변환 후 Docling 호출**

```python
# 기존 HWPX extractor는 LibreOffice → DOCX 변환 후 python-docx 사용
# 변경: 변환된 DOCX 바이트를 docling_ex로 재진입

async def extract_hwpx(file_bytes: bytes, file_name: str) -> ConvertResult:
    docx_bytes = await _libreoffice_convert(file_bytes, "hwpx", target="docx")
    from extractors.docling_ex import extract as docling_extract
    result = await docling_extract(docx_bytes, file_name.replace(".hwpx", ".docx"))
    result.source_format = "hwpx"
    return result
```

- [ ] **Step 2: 테스트 (샘플 HWPX 있으면)**

HWPX 샘플이 없으면 스킵 가능. LibreOffice 자체는 CI 환경 의존.

---

# Phase 1~3 완료 후 Regression

## Task 16 (공통): 전체 테스트 + 린트

**Files:** (없음, CI 실행)

- [ ] **Step 1: `python -m pytest tests/ -v` 전체 통과 (v2 145+ + v3 신규)**
- [ ] **Step 2: `ruff check .` 린트 통과**
- [ ] **Step 3: 실측 검증**
    - 한국어 PDF 10p: Forge 경로 `POST /convert?route=docling` → 60초 이내 완료 (PERF-01)
    - PL/SQL 1개: `POST /reverse-doc` → 180초 이내 (PERF-04)
    - MD 1MB: `POST /refine` → 100ms (PERF-03)

---

## Phase 완료 시 매뉴얼 산출

각 Phase 완료 직후 다음 매뉴얼 업데이트:

| Phase | 매뉴얼 |
|---|---|
| P1 | `C:/workspace/lightrag/track_f_forge_extension_phase1_refine.md` |
| P2 | `C:/workspace/lightrag/track_f_forge_extension_phase2_revdoc.md` |
| P3 | `C:/workspace/lightrag/track_f_forge_extension_phase3_docling.md` |

각 매뉴얼에 포함:
- 배경 / 설계 결정
- 구현 요약 (Task 번호 링크)
- 검증 결과 (실측 숫자)
- 운영 체크리스트
- 이관 가이드 (EC2)

---

## 요약 체크리스트

**Phase 0 — Preflight**
- [ ] T0. env + lifespan wiring (CF-1, CF-2, CF-4)

**Phase 1 — REFINE + CALLBACK**
- [ ] T1. forge_refine_rules + RefineRuleStore
- [ ] T2. refine/stages/* 6개
- [ ] T3. refine/validator.py
- [ ] T4. refine/ Refiner 파사드
- [ ] T5. POST /refine 엔드포인트
- [ ] T6. docs/CORTEX-INTEGRATION.md 확장

**Phase 2 — REVDOC**
- [ ] T7. forge_prompts reverse_doc 시드
- [ ] T8. revdoc/gate.py
- [ ] T9. revdoc/generator.py
- [ ] T10. POST /reverse-doc 엔드포인트

**Phase 3 — DOCLING + ROUTE**
- [ ] T11. docling 의존성 + schema + Dockerfile prewarm
- [ ] T12. extractors/docling_ex.py
- [ ] T13. DoclingLogStore
- [ ] T14. router.py 확장
- [ ] T15. HWPX → Docling

**공통**
- [ ] T16. regression + benchmark + 린트

**매뉴얼**
- [ ] track_f P1 문서
- [ ] track_f P2 문서
- [ ] track_f P3 문서
