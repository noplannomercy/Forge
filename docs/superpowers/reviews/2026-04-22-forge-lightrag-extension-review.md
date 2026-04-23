# Forge LightRAG Extension — Plan Engineering Review

> 2026-04-22 | `docs/superpowers/plans/2026-04-22-forge-lightrag-extension.md`에 대한 기술 검토

---

## 검토 입력

| 문서 | 경로 |
|---|---|
| SRS | `docs/SRS-v3-lightrag.md` |
| Design Spec | `docs/superpowers/specs/2026-04-22-forge-lightrag-extension-design.md` |
| Plan | `docs/superpowers/plans/2026-04-22-forge-lightrag-extension.md` |

## 검토 범위

- 기존 Forge 코드 (app.py, worker.py, models.py, router.py, vlm.py, job_store.py)
- 기존 v2 SRS + CLAUDE.md
- LightRAG `/documents/upload`, `/documents/text` 스펙

---

## Critical Findings (구현 전 반드시 해결)

### CF-1. Callback Payload 필드명 불일치

**문제**: Forge callback payload는 Cortex `/v1/ingest` 호환 구조.

```python
# Forge 현재 (worker.py:156)
payload = {
    "content": updated_job.result.text,
    "file_name": updated_job.file_name,
    "domain": ...,
    "metadata": updated_job.meta,
    "extract": True,
    "pre_converted": True,
    "forge_job_id": ..., "forge_status": ..., "forge_error": ...,
}
```

LightRAG는:
- `/documents/upload` → `multipart/form-data` (UploadFile) — JSON 안 받음
- `/documents/text` → `InsertTextRequest` JSON, 필드: `text`, `file_source` (이름 다름)

→ Forge를 그대로 `callback_url=http://.../documents/text` 로 쏘면 LightRAG가 `text` 필드 없어서 400 오류.

**해결 옵션**

| 안 | C1(Cortex 독립) | 복잡도 |
|---|---|---|
| (a) Forge에 `if consumer=='lightrag'` 분기 | ❌ 위반 | 낮음 |
| (b) LightRAG 측에 Forge-호환 엔드포인트 추가 (`/documents/ingest_cortex_style`) | ✅ 준수 | 중 (LightRAG fork 관리) |
| (c) **Forge에 generic `CALLBACK_FIELD_MAP` env 추가** (consumer-specific 코드 없음) | ✅ 준수 | 낮음 |
| (d) 독립 어댑터 마이크로서비스 (포트 9622) | ✅ 준수 | 높음 (서비스 +1) |

**결정: (c) — `CALLBACK_FIELD_MAP` env**

```python
# config.py 추가
callback_field_map: str | None = None  # JSON string: {"content":"text","file_name":"file_source"}
callback_keep_unmapped: bool = False   # False면 매핑 안 된 필드 제거

# worker.py _send_callback 직전
if config.callback_field_map:
    rename_map = json.loads(config.callback_field_map)
    payload = {rename_map.get(k, k): v for k, v in payload.items()}
    if not config.callback_keep_unmapped:
        payload = {k: v for k, v in payload.items() if k in rename_map.values()}
```

LightRAG 연동 시 env:
```
CALLBACK_FIELD_MAP={"content":"text","file_name":"file_source"}
CALLBACK_KEEP_UNMAPPED=false
```

→ C1 준수 (generic renaming), 범용.

**SRS 반영 필요**: CALLBACK-06 (field map) 추가.

---

### CF-2. `ConvertResult.route` 값 제약

**문제**: `models.py`에서 `route: str` 주석 `"vlm" | "extract"`. `/convert` Query의 `pattern="^(extract|vlm)$"` (app.py:111).

**해결**: `docling`, `reverse_doc`, `refine` 모두 허용.

```python
# app.py /convert Query
route: str | None = Query(None, pattern="^(extract|vlm|docling)$", ...)
# 내부 전용(reverse_doc, refine)은 /reverse-doc, /refine 전용 엔드포인트라 Query X
```

`models.py:37`의 주석 업데이트:
```python
route: str  # "vlm" | "extract" | "docling" | "reverse_doc" | "refine"
```

---

### CF-3. `/reverse-doc`의 `source_code` 전달 방식

**문제**: Plan T10에서 `source_code`를 Job 객체에 저장하려 했는데, `models.py:Job`에 해당 필드 없음. 기존 패턴(`callback_url`, `domain`)은 **Job 객체에 동적 할당**(Python duck typing) 후 worker에 전달.

**해결**: 동일 패턴 사용. DB에 저장하지 않고 메모리에서만.

```python
# app.py /reverse-doc
job = await current_store.create(file_name, "reverse_doc", "reverse_doc", ...)
job.source_code = raw.decode("utf-8", errors="replace")  # 동적 할당
job.callback_url = callback_url
asyncio.create_task(_safe_process(job, raw, "reverse_doc", ...))
```

`PostgresJobStore._row_to_job`은 source_code 읽지 않음 — DB에 저장 X.

**Plan T10 수정 필요**: Step 2 코드에서 `source_code=raw.decode(...)` 부분을 동적 할당으로 명시.

---

### CF-4. `process_job` 시그니처 확장

**문제**: Plan T10에서 `worker.py`에 `reverse_doc` 분기 추가. 현재 `process_job(job, file_bytes, route, store, config, meta_extractor, vlm_log_store, prompts)` 시그니처. Refiner·RevdocGenerator·DoclingLogStore를 어떻게 주입?

**해결**: 기존 `prompts` 같은 lazy-load 패턴 유지. 신규 dependencies를 `app.state`에 두고 `process_job`에 추가 파라미터.

```python
# app.py lifespan
a.state.refine_rule_store = InMemoryRefineRuleStore() or PostgresRefineRuleStore(pool)
await seed_refine_rules(a.state.refine_rule_store)
a.state.refiner = await Refiner.from_store(a.state.refine_rule_store)
a.state.revdoc_generator = ReverseDocGenerator(
    vlm=VLMClient(config),
    prompt_store=a.state.prompt_store,
    refiner=a.state.refiner,
)
a.state.docling_log_store = PostgresDoclingLogStore(pool) or InMemoryDoclingLogStore()

# process_job 시그니처
async def process_job(job, file_bytes, route, store, config, *,
                      meta_extractor=None, vlm_log_store=None, prompts=None,
                      refiner=None, revdoc_generator=None, docling_log_store=None):
```

**Plan 수정**: T5/T10/T12에 app.state 주입 Step 명시.

---

### CF-5. PromptStore는 PG 전용

**문제**: `job_store.py:PromptStore`는 asyncpg pool 필요. DB 없는 환경(InMemory)에서 reverse_doc 프롬프트는 어디서 로드?

**해결**: `PromptStore`도 InMemory 구현 추가 (현재 `VLMLogStore`는 PG 전용, `PromptStore`도 동일). v2 하네스에서 DB 없으면 `SEMANTIC_PROMPT`, `META_PROMPT` 하드코딩 fallback. 동일 패턴:

- DB 있으면 `PostgresPromptStore` (현재 `PromptStore`)
- DB 없으면 하드코딩 프롬프트 + InMemory
- 결과: `revdoc/prompts/reverse_doc_v1.md`를 import해서 DB 없을 때 기본값

```python
# job_store.py
class PromptStore(ABC):
    @abstractmethod
    async def get_active(self, prompt_type: str) -> dict | None: ...

class InMemoryPromptStore(PromptStore):
    def __init__(self, defaults: dict[str, str]):
        self._data = {t: {"text": txt, "version": 1, "is_active": True} for t, txt in defaults.items()}
    async def get_active(self, prompt_type): return self._data.get(prompt_type)

class PostgresPromptStore(PromptStore):  # 기존
    ...
```

**Plan 수정**: T7 Step에 InMemoryPromptStore 추가. app.py lifespan에 DB 분기.

---

### CF-6. Docling `Dockerfile` prewarm vs 현실

**문제**: Plan T11이 `Dockerfile`에 `RUN python -c "from docling.document_converter import DocumentConverter; DocumentConverter()"`로 모델 prewarm. 근데 이러면 **이미지 빌드 시** 506MB HF 다운로드 → 이미지 크기 폭증 + 빌드 시간 +5분.

**해결 옵션**

| 안 | 트레이드오프 |
|---|---|
| (a) Dockerfile prewarm | 이미지 +500MB, 빌드 느림, 런타임 빠름 |
| (b) 런타임 첫 호출 시 다운로드 | 이미지 작음, 빌드 빠름, 첫 변환 느림(+2분) |
| (c) Volume mount (`~/.cache/huggingface`) | 호스트 공유, 이미지 작음. 배포 시 볼륨 prewarm 스크립트 |

**결정: (c) — Volume mount + 배포 시 prewarm 스크립트**

```dockerfile
# Dockerfile - prewarm 제거
# 볼륨 마운트 가이드는 docker-compose.yml에 명시

# docker-compose.integration.yml
  forge:
    volumes:
      - hf-cache:/root/.cache/huggingface  # 모델 캐시 볼륨
volumes:
  hf-cache:
```

```bash
# 배포 시 1회 prewarm (별도 스크립트 scripts/prewarm_docling.sh)
docker exec forge python -c "from docling.document_converter import DocumentConverter; DocumentConverter()"
```

**Plan 수정**: T11 Step 3 교체.

---

### CF-7. `schema.sql` 전체 재적용 시 `forge_jobs` 확장

**문제**: `_apply_schema()`가 매 startup에 전체 schema.sql 실행. `IF NOT EXISTS`라 새 테이블(`forge_refine_rules`, `forge_docling_logs`)은 OK. 하지만 v3에서 기존 `forge_jobs`에 **새 필드 추가**가 필요하면 `ALTER TABLE IF NOT EXISTS COLUMN`이 필요 (PG 16 지원).

**확인**: v3에서 `forge_jobs`에 새 필드 추가 필요한가?
- callback_url → 이미 메모리에서만 전달, DB 저장 X (기존 패턴)
- source_code → 동일, DB 저장 X
- reverse_doc에서 `prompt_version` 활용 → 기존 컬럼 존재, 재사용

→ **forge_jobs 스키마 변경 불필요**. OK.

단, `schema.sql`에 기존 `ALTER TABLE forge_jobs ADD COLUMN IF NOT EXISTS deleted_at ...` 같은 패턴 있음. v3 테이블 추가만 하면 멱등.

**Plan 반영**: schema.sql 수정 시 `CREATE TABLE IF NOT EXISTS`만. ALTER 불필요.

---

## 열린 질문 해결 (Spec Q1~Q8)

| # | 질문 | 답 | 근거 |
|---|---|---|---|
| **Q1** | VLM_CONCURRENCY Semaphore를 Docling/REVDOC과 공유? | **공유로 시작, Phase 3 벤치마크 후 분리 판단** | 2코어 VPS에서 동시 3건이 한계. 별도 Semaphore는 RES-01 초과 위험 |
| **Q2** | Docling 모델 prewarm 시점 | **배포 스크립트**로 (CF-6 참조). Dockerfile 빌드 시점 X | 이미지 크기 +500MB 회피 |
| **Q3** | REFINE 기본 임계값 저장 위치 | **`forge_refine_rules`의 `stage='validator'` row** | 규칙 버전 관리 통합 |
| **Q4** | REVDOC LLM = VLM_MODEL 공용? 별도? | **MVP는 공용. `config.revdoc_model` optional env 준비, None이면 `vlm_model` fallback** | 당장은 저비용, 확장 여지 |
| **Q5** | `/reverse-doc` 최대 크기 | **200KB** | 프로시저 1건 기준 충분. SRS REVDOC-01 문서화 |
| **Q6** | HWPX 우선순위 | **Phase 3 포함** | LibreOffice 경로 재활용, 저비용 |
| **Q7** | Admin API `/refine` 통계 | **별도 API X. 기존 `GET /jobs?source_format=refine`으로 자연 지원** | 기존 Admin 재사용 |
| **Q8** | `/refine` 응답에 rule_version | **포함. `rule_versions: {encoding: 1, newline: 2, ...}`** | SRS REFINE-03 상세화 |

---

## Minor Findings

### MF-1. Prompt 캐시 타이밍

현재 Forge `a.state.prompts`는 startup에만 로드. 새 버전 upsert해도 서버 재시작 필요. v3의 `reverse_doc` 프롬프트도 동일 제약. 기존 설계 철학이라 유지.

**Plan 반영**: Admin API로 프롬프트 버전 변경 후 "재시작 필요" 문서화만.

### MF-2. VLM `process_text` 신규 메서드

Plan T9에서 `VLMClient.process_text()` 추가 필요. 기존 `process_batch()`는 이미지 배열 받음. 텍스트 전용 메서드 추가 시:
- `Semaphore`, retry, 로깅 동일 패턴
- 기존 `process_batch` 리팩토링: 공통 `_call_llm()` 내부 메서드로 분리 → `process_batch`와 `process_text` 둘 다 재사용

**Plan 수정**: T9 Step 2에 리팩토링 경고 + 기존 테스트 회귀 체크 명시.

### MF-3. `domain` 파라미터 관리

Forge는 callback payload에 `domain` 넣음 (Cortex 인덱싱 분류). LightRAG는 `workspace` 개념. 매핑은 consumer 측에서 처리해야 C1 준수.

→ `CALLBACK_FIELD_MAP`이 `"domain": "workspace"` 매핑도 커버.

### MF-4. `/refine` 엔드포인트의 Body 형태

Plan T5는 multipart + Form. 근데 MD는 보통 raw text. `application/json` 또는 `text/plain`도 지원하면 DX 좋음.

**Plan 보완**: T5 Step 2에 body 타입 3종 지원 (multipart / raw text / json) 언급.

### MF-5. `extractors/__init__.py`의 EXTRACTORS dict

현재 `EXTRACTORS = {"docx": extract_docx, "xlsx": extract_xlsx, ...}` 형태. `docling_ex`는 단일 extractor가 아니라 PDF 라우팅의 옵션 중 하나. EXTRACTORS dict에 추가할지 여부:

**결정**: EXTRACTORS에 추가 X. worker.py에서 `route == "docling"` 분기로 직접 호출. 이유:
- EXTRACTORS는 `source_format` 기반 dispatch
- docling은 `route` 기반 선택 (같은 PDF도 docling/extract/vlm 선택)

**Plan 반영**: T12 Step에 명시.

---

## 작업 위치 매핑 (🟢 로컬 / 🔵 VPS 필요 / 🟡 선택)

| Task | 위치 | 이유 |
|---|---|---|
| T1 schema + RuleStore | 🟢🔵 | InMemory 로컬 OK, PG는 VPS |
| T2 refine/stages/* | 🟢 | 순수 Python |
| T3 validator | 🟢 | 순수 Python |
| T4 Refiner | 🟢 | InMemoryStore 충분 |
| T5 `/refine` 엔드포인트 | 🟢 | uvicorn + InMemory |
| T6 CORTEX-INTEGRATION.md | 🟢 | 문서 |
| T7 프롬프트 시드 + InMemoryPromptStore | 🟢🔵 | |
| T8 revdoc/gate.py | 🟢 | 순수 Python |
| T9 revdoc/generator.py + vlm.process_text | 🟢 | LLM mock |
| T10 `/reverse-doc` 엔드포인트 | 🟢 | |
| T11 docling 의존성 + schema + volume 마운트 | 🟢🔵 | |
| T12 extractors/docling_ex.py | 🟢 | **이미 로컬 실측 완료** |
| T13 DoclingLogStore | 🟢🔵 | |
| T14 router.py 확장 | 🟢 | |
| T15 HWPX | 🟡🔵 | LibreOffice 필요 |
| T16 regression | 🟢🔵 | 로컬 pytest + VPS PG 통합 |

→ **T1~T16 중 12개가 로컬 OK**. VPS는 마지막 통합·배포만.

---

## 테스트 전략 보완

### Integration Test Harness

로컬에서 LightRAG callback까지 E2E 테스트하려면:

**옵션 A**: Mock LightRAG 서버 (pytest fixture)
```python
@pytest.fixture
async def mock_lightrag():
    app = FastAPI()
    @app.post("/documents/text")
    async def text(req: dict):
        return {"status": "success", "track_id": "mock-track-id"}
    # ...
```

**옵션 B**: VPS LightRAG 직접 호출 (flakier, 네트워크 의존)

**결정**: **옵션 A 기본, VPS 호출은 `--integration-vps` 플래그로만**.

### Performance Test

PERF-01(Docling 60초), PERF-03(Refine 100ms), PERF-04(Revdoc 180초)은 **로컬에서도 측정 가능**. pytest-benchmark + VPS 실측 후 최종 판정 2차 보강.

---

## Plan 업데이트 목록

구현 시작 전 Plan 파일에 반영:

1. 각 Task 헤더에 🟢/🔵 태그 추가
2. CF-1 ~ CF-7 반영 (Step 세부)
3. 새 Task 추가: **T0. Preflight** (env 설계 + lifespan wiring 일괄)
4. MF-2: vlm.py 리팩토링 경고
5. MF-4: `/refine` body 타입 3종
6. MF-5: EXTRACTORS dict 불변 명시

---

## CLAUDE.md 업데이트 목록

다음 항목 추가/수정:

1. **제약 C6 신규**: "신규 모듈(refine/·revdoc/·extractors/docling_ex.py)은 `from lightrag import ...` 금지 (C1 연장)"
2. **준수 S6 신규**: "신규 extractor는 기존 S4 시그니처(`async def extract(file_bytes, file_name) -> ConvertResult`) 준수"
3. **준수 S7 신규**: "LLM 호출은 vlm.py 경유 (Semaphore + retry 재사용), 직접 httpx 호출 금지"
4. **스택 추가**: `docling>=2.90` (CPU PDF 파서, 한국어 표 보존)
5. **구조 테이블 확장**: refine/, revdoc/, extractors/docling_ex.py 행 추가
6. **참조 문서 추가**: SRS-v3, spec, plan, review 4개
7. **환경 제약 신규 섹션**: "개발 환경 — 로컬 Windows (Docker 없음), 통합 테스트는 VPS Postgres + LightRAG"

---

## TODO.md 업데이트 목록

v3 섹션 신규 추가:

```markdown
## v3 — LightRAG Extension (진행 중 — 2026-04-22 시작)

> SRS: docs/SRS-v3-lightrag.md | Spec: docs/superpowers/specs/2026-04-22-forge-lightrag-extension-design.md
> Plan: docs/superpowers/plans/2026-04-22-forge-lightrag-extension.md
> Review: docs/superpowers/reviews/2026-04-22-forge-lightrag-extension-review.md

### Phase 1 — REFINE + CALLBACK
- [ ] T0. Preflight (env + lifespan)
- [ ] T1. forge_refine_rules + RuleStore
- [ ] T2. refine/stages/* 6개
- [ ] T3. refine/validator.py
- [ ] T4. refine/ Refiner
- [ ] T5. POST /refine 엔드포인트
- [ ] T6. CORTEX-INTEGRATION.md

### Phase 2 — REVDOC
- [ ] T7. reverse_doc 프롬프트 시드 + InMemoryPromptStore
- [ ] T8. revdoc/gate.py
- [ ] T9. revdoc/generator.py + vlm.process_text
- [ ] T10. POST /reverse-doc

### Phase 3 — DOCLING + ROUTE
- [ ] T11. docling 의존성 + schema + volume
- [ ] T12. extractors/docling_ex.py
- [ ] T13. DoclingLogStore
- [ ] T14. router.py 확장
- [ ] T15. HWPX

### Regression + 매뉴얼
- [ ] T16. regression + benchmark + 린트
- [ ] track_f_forge_extension_phase1 매뉴얼
- [ ] track_f_forge_extension_phase2 매뉴얼
- [ ] track_f_forge_extension_phase3 매뉴얼
```

---

## 최종 GO/NO-GO

| 항목 | 판정 |
|---|---|
| SRS 완성도 | ✅ |
| Design Spec 완성도 | ✅ |
| Plan 구체성 | ⚠️ CF-1~7 반영 후 GO |
| 기존 코드 충돌 | ✅ 해결됨 (CF 항목들) |
| 열린 질문 | ✅ Q1~Q8 모두 해결 |
| 환경 제약 (로컬 Docker X) | ✅ 로컬 70% 가능, VPS는 통합만 |
| 리스크 최대 | CF-1 callback payload — 해결됨 (CALLBACK_FIELD_MAP) |

**→ Plan 수정 후 구현 GO.**

---

## 다음 스텝

1. Plan 파일에 CF-1~7 + 🟢/🔵 태그 + T0 추가 반영
2. CLAUDE.md 업데이트
3. TODO.md v3 섹션 추가
4. CF-1 대응: `config.py`에 `callback_field_map`, `callback_keep_unmapped` 추가 (T0에 포함)
5. `superpowers:executing-plans` 또는 `subagent-driven-development`로 Phase 1부터 착수
