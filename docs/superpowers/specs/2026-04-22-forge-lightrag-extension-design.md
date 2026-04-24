# Forge LightRAG Extension — Design Spec

> 2026-04-22 | Docling extractor 통합, `/refine`·`/reverse-doc` 엔드포인트 추가, LightRAG consumer 연계

관련: `docs/SRS-v3-lightrag.md` (요구사항 43개)

---

## 배경

LightRAG가 Cortex를 대체 consumer로 진입. Forge는 consumer-agnostic 원칙(C1) 유지하면서 3가지 확장 필요:

1. **Docling 통합** — 한국어 PDF/표 품질 향상 (MarkItDown·MinerU 비채용 근거 실측 완료)
2. **`/refine`** — 이미 텍스트인 MD의 6단계 정제
3. **`/reverse-doc`** — PL/SQL 코드 → 자연어 업무 문서

## 목표

- SRS-v3 기능 요구사항 43개 충족
- v2 SRS 21개 요구사항 회귀 없음
- C1 제약 유지 (Forge 코드에서 `from lightrag import ...` 금지)
- 기존 Forge 패턴 100% 재사용 (Job / PromptStore / Admin / VLM 클라이언트 / `_safe_process`)

---

## 설계 결정사항

| 결정 | 선택 | 이유 |
|---|---|---|
| Docling 통합 위치 | 새 `extractors/docling_ex.py` | S4 시그니처 준수, 기존 extractor와 동급 처리 |
| Docling 호출 방식 | sync `DocumentConverter().convert()`를 `asyncio.to_thread`로 감싸 async 래핑 | Docling 자체는 sync. worker의 async flow 유지 |
| Docling fallback | Docling OOM·예외 시 `extractors/pdf.py`(pypdfium2)로 자동 재시도 | RES-01(8GB RAM) 안전망. quality.fallback=true 기록 |
| CPU 모드 | `PdfPipelineOptions.accelerator_options.device='cpu'` 강제 | GPU 없음 전제 (로컬·VPS 공통) |
| 모델 캐시 위치 | HF 기본(`~/.cache/huggingface`) | Docker 컨테이너엔 `/root/.cache/huggingface` 볼륨 마운트 권장 |
| HWPX 처리 | 기존 `extractors/office.py` LibreOffice → DOCX 파이프라인 뒤에 Docling 연결 | 재사용, 신규 코드 최소 |
| REFINE 6단계 | 순수 Python 모듈 `refine/` 패키지 6개 stage 파일 | torch 무관, 빠름(100ms 요구) |
| REFINE 실행 모드 | 동기 기본 + `?async=true` 옵션으로 Job화 | PERF-03 동기 100ms 충족, 큰 파일은 Job |
| REFINE 규칙 버전관리 | `forge_refine_rules` 신규 테이블 (PromptStore 패턴 모방) | 규칙이 정규식·JSON 데이터지 프롬프트 텍스트 아님 → 별도 테이블이 명확 |
| REVDOC LLM 호출 | 기존 `vlm.py`의 `process_batch`를 "purpose='reverse_doc'"로 재사용 | S1 Semaphore + S2 retry 재활용. VLM=Vision만 다루지 않고 LLM 일반화된 용도 |
| REVDOC 품질 게이트 | post-process 검증기 `revdoc/gate.py` | 섹션 헤더 grep, Traceability 삼각 정규식, 길이 체크 |
| REVDOC 게이트 실패 재시도 | 프롬프트에 feedback 추가해 최대 2회 | S2 retry와 독립. 게이트 피드백 주입 루프 |
| REVDOC 출력 자동 refine | REVDOC 내부에서 `/refine` 모듈 직접 호출 (HTTP X) | 같은 프로세스라 오버헤드 회피 |
| Callback Payload | 기존 v2 스펙 그대로 | C1 준수. LightRAG용 필드 추가 금지 |
| Callback URL 포맷 검증 | 기존 로직 재사용 | 별도 LightRAG 전용 validator 금지 |
| Router 확장 | `router.py`에 `route='docling'` 추가, PDF 기본 경로 변경 | ROUTE-06,08 구현 |
| 동시성 | Docling·REVDOC 둘 다 `VLM_CONCURRENCY` Semaphore 공용 | 2코어 VPS 보호. 동시 최대 3건 기본 |

---

## 모듈 배치

```
Forge/
├── app.py                     # (변경) /refine, /reverse-doc 라우트 등록
├── router.py                  # (변경) docling 라우트 추가 (ROUTE-06~09)
├── worker.py                  # (변경) route=='docling'|'refine'|'reverse_doc' 분기
├── models.py                  # (변경) RefineRequest, ReverseDocRequest 등 Pydantic
├── schema.sql                 # (변경) forge_refine_rules, forge_docling_logs, forge_prompts(type='reverse_doc')
├── job_store.py               # (변경) RefineRuleStore 추가 (PromptStore 패턴)
├── extractors/
│   ├── docling_ex.py          # (신규) DOCLING-01~08
│   └── pdf.py                 # (변경) fallback 진입점 노출
├── refine/                    # (신규)
│   ├── __init__.py            # Refiner 파사드
│   ├── pipeline.py            # 6단계 실행 + 리포트
│   ├── stages/
│   │   ├── encoding.py        # REFINE-02 (1)
│   │   ├── newline.py         # (2)
│   │   ├── special_char.py    # (3)
│   │   ├── frontmatter.py     # (4)
│   │   ├── codefence.py       # (5)
│   │   └── traceability.py    # (6)
│   └── validator.py           # REFINE-04 (UTF-8/개행/한글비율/최소길이)
├── revdoc/                    # (신규)
│   ├── __init__.py            # ReverseDocGenerator 파사드
│   ├── generator.py           # REVDOC-01,04,06 (LLM 호출 + 재시도 루프)
│   ├── gate.py                # REVDOC-05 (섹션/삼각/길이)
│   └── prompts/
│       └── reverse_doc_v1.md  # REVDOC-03 초기 시드
└── tests/
    ├── test_docling_extractor.py
    ├── test_refine_pipeline.py
    ├── test_refine_validator.py
    ├── test_revdoc_generator.py
    └── test_revdoc_gate.py
```

---

## 기능별 상세 설계

### 1. DOCLING

**진입**:
```
POST /convert?route=docling (또는 PDF 자동 라우팅, ROUTE-06)
  → worker.py 에서 extractors/docling_ex.py 호출
```

**핵심 코드 윤곽** (`extractors/docling_ex.py`):
```python
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
import asyncio

_CONVERTER = None

def _get_converter():
    global _CONVERTER
    if _CONVERTER is None:
        opts = PdfPipelineOptions()
        opts.accelerator_options.device = "cpu"
        _CONVERTER = DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
        )
    return _CONVERTER

async def extract(file_bytes: bytes, file_name: str) -> ConvertResult:
    t0 = time.time()
    try:
        # Docling은 파일 경로 요구 → tempfile 사용
        async with _semaphore:   # VLM_CONCURRENCY와 공용
            result = await asyncio.to_thread(_convert_sync, file_bytes, file_name)
        latency_ms = int((time.time() - t0) * 1000)
        await _log_docling(pages=result.pages, latency_ms=latency_ms, fallback=False)
        return result
    except (MemoryError, RuntimeError) as e:
        logger.warning(f"Docling failed, fallback to pypdfium2: {e}")
        await _log_docling(pages=0, latency_ms=0, fallback=True, reason=str(e))
        from extractors.pdf import extract as pdf_fallback
        return await pdf_fallback(file_bytes, file_name)
```

**로깅**: `forge_docling_logs` 테이블에 페이지 수·시간·fallback 여부 기록 (DOCLING-08).

### 2. ROUTE 확장

**변경점 (`router.py`)**:
```python
# 기존 ROUTE-04: chars_per_mb < 100 이면 vlm, 아니면 extract
# 변경: chars_per_mb < 100 이면 vlm, 아니면 docling (기본)
# route_override='extract'면 기존 pypdfium2 유지 (수동 fallback 용)

if source_format == "pdf":
    if chars_per_mb < VLM_THRESHOLD:
        return "vlm"
    if route_override == "extract":
        return "extract"  # 기존 pypdfium2
    return "docling"     # 기본
```

HWPX: `extractors/office.py` → LibreOffice → DOCX 바이너리 → Docling 경로 재진입 (ROUTE-09).

### 3. REFINE

**파사드 (`refine/__init__.py`)**:
```python
class Refiner:
    def __init__(self, rule_store: RefineRuleStore):
        self.stages = [
            EncodingStage(rule_store.active('encoding')),
            NewlineStage(rule_store.active('newline')),
            SpecialCharStage(rule_store.active('special_char')),
            FrontmatterStage(rule_store.active('frontmatter')),
            CodefenceStage(rule_store.active('codefence')),
            TraceabilityStage(rule_store.active('traceability')),
        ]
        self.validator = Validator(rule_store.active('validator'))

    def refine(self, raw: bytes | str) -> RefineResult:
        text = raw
        report = RefineReport()
        for stage in self.stages:
            text, stage_report = stage.apply(text)
            report.add(stage_report)
        verdict = self.validator.check(text)
        return RefineResult(text=text, report=report, gate=verdict)
```

**엔드포인트** (`app.py`):
- 동기: `POST /refine` — 기본. 100ms 이내 응답
- 비동기: `POST /refine?async=true` — Job 생성, `/result/{job_id}` 조회

**응답 형식**:
```json
{
  "refined_text": "...",
  "report": {
    "encoding": {"applied": true, "from": "cp949", "changes": 0},
    "newline": {"applied": true, "replacements": 142},
    "special_char": {"applied": true, "replacements": 7},
    "frontmatter": {"applied": true, "stripped_lines": 5},
    "codefence": {"applied": false, "reason": "not requested"},
    "traceability": {"applied": true, "sentences_created": 12}
  },
  "quality": {
    "gate": "pass",
    "utf8": true,
    "newlines": 142,
    "korean_ratio": 0.78,
    "length": 15340
  }
}
```

### 4. REVDOC

**흐름**:
```
POST /reverse-doc (file=code)
  → Job 생성
  → revdoc/generator.py
      → PromptStore.active('reverse_doc') 로드
      → vlm.process_batch(source_code, prompt, purpose='reverse_doc')
         (S1 Semaphore + S2 retry 자동)
      → gate.check(generated_md)
      → 실패 시 피드백 프롬프트 추가 + 재시도 (최대 2회)
  → Refiner.refine(generated_md) 직접 호출 (HTTP 아님)
  → Job에 result_text + quality + prompt_version 저장
  → callback_url 있으면 push
```

**게이트 검증 (`revdoc/gate.py`)**:
```python
REQUIRED_SECTIONS = [
    "업무목적", "처리흐름", "입력/출력",
    "규칙/예외", "근거", "추적성", "관련업무"
]

def check(md: str) -> GateVerdict:
    # 1. 섹션 7개 헤더 존재
    for section in REQUIRED_SECTIONS:
        if not re.search(rf"^##+\s*{section}", md, re.M):
            return fail(f"section missing: {section}")
    # 2. Traceability 삼각: Rule, Condition, Evidence 각 1개 이상
    # 3. 길이 ≥ 임계 (기본 800자)
    ...
```

### 5. CALLBACK 확장

**변경 없음**. 기존 v2 callback 스펙 그대로. LightRAG는 `callback_url=https://.../documents/upload` 전달하면 됨. 페이로드는 기존과 동일 (`pre_converted=true`, `X-API-Key`). Forge 코드에 LightRAG 이름 박힌 분기 금지 (COMP-02).

**문서 추가**: `docs/CORTEX-INTEGRATION.md`에 "LightRAG 연계 예제" 섹션 추가 (명칭은 "Consumer 예시 — LightRAG" 정도).

---

## 데이터 흐름

### 시나리오 1: 한국어 정책 PDF → LightRAG

```
1. POST /convert?callback_url=https://lightrag/documents/upload
      file=policy.pdf
2. router.py: source_format=pdf, chars_per_mb=200 → route=docling
3. worker.py: extractors/docling_ex.py 호출
   → CPU Semaphore 획득 → Docling 변환 (30~60s)
   → 표·섹션·각주 보존된 MD 반환
4. worker.py: 자동 /refine 파이프라인 적용 (내부 호출)
5. worker.py: DB 저장 + callback_url로 push
6. LightRAG: MD 수신 → 청크·엔티티·관계 추출 → KG 저장
```

### 시나리오 2: PL/SQL 역문서 생성

```
1. POST /reverse-doc
      file=PKG_LOAN_BATCH.pkb
      callback_url=https://lightrag/documents/upload
2. worker.py: revdoc/generator.py 진입
3. generator: PromptStore.active('reverse_doc') 로드 (prompt_version 기록)
4. vlm.process_batch(source_code, prompt, purpose='reverse_doc')
   → 기본 LLM으로 생성 (Vision 불필요, 텍스트만)
5. gate.check(generated): 섹션·삼각·길이 검증
   → 실패 → feedback 프롬프트 추가 → 재생성 (최대 2회)
6. Refiner.refine(generated): 6단계 정제 적용
7. DB 저장 + callback push
```

### 시나리오 3: MD 정제 단독 호출

```
1. POST /refine (body=raw MD or multipart)
2. Refiner.refine(text): 6단계 순차 적용
3. Validator.check(refined): 품질 게이트
4. 동기 응답 (< 100ms)
5. (선택) callback_url 있으면 push
```

---

## 엣지 케이스 / 실패 모드

| 케이스 | 동작 |
|---|---|
| Docling OOM (메모리 부족) | `MemoryError` catch → pypdfium2 fallback. `quality.fallback=true`, `fallback_reason` 기록 |
| Docling 모델 다운로드 실패 (첫 실행 네트워크 오류) | 기동 시 prewarm 헬스체크 OK, 런타임 실패 시 fallback. 주기적 재시도 |
| 한국어 비율 < 임계 (0.1) | REFINE quality.gate='fail', 사유 "low korean ratio". Job은 completed (게이트는 정보성) |
| cp949 디코드 성공했으나 한글 깨짐 (혼재 인코딩) | REFINE.encoding stage에서 chardet 신뢰도 기록. validator가 깨진 문자 비율 체크 |
| REVDOC 2회 재시도 후도 게이트 실패 | `quality.gate='fail'`, Job status=completed, error=null. 소비자가 gate.pass로 필터 |
| REVDOC의 vlm.process_batch가 모두 실패 (S2 3회 retry 실패) | Job status=failed, error="LLM call exhausted" |
| callback_url 지정했으나 도달 불가 | 기존 로직: 3회 retry 후 DB만 보존. Job 자체는 completed |
| Docling이 HWPX 변환(LibreOffice 경유) 중 DOCX 깨짐 | extractors/office.py 에러 → worker 레벨에서 route=extract fallback |
| `/refine` 빈 입력 | 400 Bad Request |
| `/reverse-doc` 지원 안 하는 확장자 | 400 Bad Request, 지원 목록 안내 |

---

## 테스트 전략

| 레벨 | 대상 | 도구 |
|---|---|---|
| Unit | refine/stages/* 각 단계 | pytest, 고정 샘플 입력 |
| Unit | refine/validator | pytest, 경계값 (한글 비율 0.09/0.10/0.11) |
| Unit | revdoc/gate | pytest, 섹션 누락·삼각 미충족 케이스 |
| Integration | extractors/docling_ex | pytest, arXiv 영문 PDF + 한국은행 10p PDF (fixtures/ 에 저장) |
| Integration | `/refine` 엔드포인트 | httpx AsyncClient, 18 docs 샘플 |
| Integration | `/reverse-doc` | LLM mock + real small PKG 샘플 |
| E2E | callback 경로 | mock LightRAG 서버 띄우고 end-to-end 검증 |
| Regression | 기존 145+ tests | `python -m pytest tests/ -v` 전체 통과 |
| Performance | Docling 10p 한국어 | `pytest-benchmark`, 목표 ≤ 60s |

fixtures:
- `tests/fixtures/bok_fsr_p1-10.pdf` (한국은행 10p)
- `tests/fixtures/attention_short.pdf` (arXiv 영문 1~3p)
- `tests/fixtures/pkg_sample.pkb` (PL/SQL 짧은 샘플)

---

## 롤아웃 / Phase 매핑

| Phase | 포함 ID | 의존성 |
|---|---|---|
| **P1** | REFINE-01~07, CALLBACK-01~05, COMP-01~04 | 없음 (기존 Forge만) |
| **P2** | REVDOC-01~08 | P1의 Refiner 재사용 |
| **P3** | DOCLING-01~08, ROUTE-06~09, PERF-01~02, RES-01~03 | 없음 (독립) |
| **P4** | (별도 SRS) | 전체 |

P1·P3은 **병렬 가능**. P2는 P1의 Refiner 필요.

---

## 열린 질문 (plan-eng-review에서 해결)

| # | 질문 | 예비 답 |
|---|---|---|
| Q1 | `VLM_CONCURRENCY`를 Docling/REVDOC과 공유 시 실질 동시성이 줄어든다. 별도 Semaphore 필요? | 당장 공용, Phase 3 측정 후 분리 판단 |
| Q2 | Docling 모델 다운로드를 이미지 빌드 타임에 미리 할지 / 첫 런타임에 할지 | Dockerfile에 prewarm 스크립트 추가 권장 (이미지 크기 +506MB 수용) |
| Q3 | REFINE 6단계의 기본 설정(임계값)은 어디 저장? | `forge_refine_rules` 에 stage='validator' 레코드로 |
| Q4 | REVDOC의 LLM은 VLM_MODEL과 동일? 별도 `REVDOC_MODEL`? | MVP는 동일, 후속에서 분리 고려 |
| Q5 | `/reverse-doc` 입력 최대 크기? | 200KB (MAX_FILE_SIZE와 별개). 한 파일 = 한 프로시저 정도 |
| Q6 | HWPX 지원 우선순위? | Phase 3 포함. LibreOffice 경로 재사용으로 저비용 |
| Q7 | Admin API에서 `/refine`, `/reverse-doc` Job 검색·통계 제공 필요? | 기존 `GET /jobs?source_format=refine` 으로 자연 지원. 통계는 `/stats/models`에 type 차원 추가 |
| Q8 | `/refine` 의 rule version을 응답에 포함할지 | 포함. report에 `rule_versions: {encoding: 1, newline: 2, ...}` |

---

## SRS ID ↔ 구현 모듈 매핑

| SRS 카테고리 | SRS ID 범위 | 주 구현 파일 |
|---|---|---|
| DOCLING | 01~08 | `extractors/docling_ex.py`, `schema.sql`, `worker.py` |
| ROUTE | 06~09 | `router.py`, `extractors/office.py` |
| REFINE | 01~07 | `refine/*`, `app.py`, `job_store.py`, `schema.sql` |
| REVDOC | 01~08 | `revdoc/*`, `app.py`, `vlm.py` 재사용, `refine/*` 재사용 |
| CALLBACK | 01~05 | 변경 없음 + `docs/CORTEX-INTEGRATION.md` 확장 |
| PERF | 01~04 | `tests/test_performance.py` + `vlm.py` Semaphore 공용 |
| RES | 01~03 | `Dockerfile` prewarm + 볼륨 마운트 가이드 |
| COMP | 01~04 | CI: `pytest tests/ -v` 전체 통과 + lint (`ruff check .`) |
