# Revdoc Gate Simplification — 설계 스펙

- **Date**: 2026-04-24
- **Branch**: feature/v3-lightrag-extension
- **Related**: `docs/superpowers/specs/2026-04-22-forge-lightrag-extension-design.md` (원본 v3 설계)
- **Status**: eng-review 반영 완료 → writing-plans 대기

**eng-review 반영 이력 (2026-04-24)**:
- §4.3.2: 텍스트 정규화(`_normalize_prompt_text`) 추가 — CRLF/LF, trailing whitespace 차이로 인한 version 스팸 방지
- §4.3.3: `seed_prompts` docstring에 시드 메커니즘 병행 이유 명시 (DRY 우려 해소)
- §4.5: 단일 워커 전제 명시 + 멀티 워커 전환 시 `pg_advisory_lock` 후속 작업 연결
- §5.3: 테스트 대상 파일 `test_prompt_store.py`로 확정 + 정규화 엣지 케이스 3건 추가 (총 6건)
- §5.4: fixture 재구성을 필수 task로 승격 + 구체 checklist
- §5.5: 회귀 샘플 2-3건 추가 — 이전 v1 pass 결과물이 신규 gate에서도 pass하는지 검증
- §5.6: 수동 품질 체크를 완료 판정 게이트로 명시 — 각 섹션 최소 1문단, placeholder 금지
- §9: advisory lock·품질 자동 게이트 후속 작업 추가

---

## 1. 배경

2026-04-23 Forge v3 LightRAG Extension (23 commits, 269 tests) 라이브 테스트 결과, `/reverse-doc` 엔드포인트의 **게이트(`revdoc/gate.py`)가 멀쩡한 LLM 출력을 탈락시키는 문제** 관측. 3회 재시도 후 최종 실패하는 사례가 실제 샘플(`discount.pkb`)에서 재현됨.

근본 원인: 게이트의 **추적성 삼각 검사**가 `Rule:` / `Condition:` / `Evidence:` literal 콜론형만 매칭하도록 구현되어 있어, LLM이 자주 출력하는 다른 형식(`**Rule**:`, `| Rule |`, `Rule "..."`)을 전부 실패로 판정.

초기에는 이 정규식을 확장하는 방향(파이프·볼드 등 허용)으로 논의했으나, **재검토 결과 추적성 검사 자체가 현 시점에 의미 없음**을 확인:

- `/reverse-doc`은 RAG·그래프를 참조하지 않는 **단순 LLM 원샷 변환**. 진짜 추적성(파일:라인이 실제 코드와 매칭) 검증은 어차피 하지 않음.
- 정규식으로 "Rule:" 키워드 찾기는 **추적성 시늉**일 뿐 추적성이 아님.
- LightRAG이 이 출력을 ingest할 때 필요한 건 "키워드 존재"가 아니라 "도메인 설명이 풍부함". 형식 강제는 의미 퇴색.
- 컴플라이언스/감사처럼 엄격한 추적성이 구체적으로 요구되는 시점이 아님 (초반 적용 단계).

따라서 본 스펙은 **게이트 단순화**를 목표로 한다. 추적성 검사를 제거하고, 게이트를 "LLM 출력이 완전히 망가진 경우만 거르는 최소 안전장치"로 축소한다.

관련 백로그: `memory/project_reverse_doc_rag_backlog.md` (RAG 통합 검토 보류 확정)

---

## 2. 목표 / 비목표

### 2.1 목표

- `revdoc/gate.py`에서 추적성 삼각(Rule/Condition/Evidence) 검사 제거.
- 게이트를 **섹션 존재 + 최소 길이 + 비어있지 않음** 3가지로 축소.
- 프롬프트를 **서술적 자유도** 쪽으로 완화 (포맷 강제 삭제).
- 파일·DB 프롬프트 배포가 **파일 변경 시 자동 신규 버전 생성**되도록 전환 (기존 `seed_if_empty`는 버전 업그레이드 안 됨).
- 2026-04-23 실패 샘플(`discount.pkb`)이 **1-attempt로 통과**하는 것을 실측 검증.

### 2.2 비목표

- RAG/그래프 참조 역문서 생성 (별도 백로그, `project_reverse_doc_rag_backlog.md`).
- 5컬럼 추적성 테이블 강제 (프롬프트 고도화).
- 진짜 추적성 검증 (Evidence의 파일:라인이 실재 코드인지).
- 다른 프롬프트(`semantic_batch`, `meta_extract`)의 자동 업그레이드 — 이번 스코프 밖. 필요 시 후속 작업.
- 게이트 retry 횟수·백오프 전략 변경 (현행 유지).

---

## 3. 영향 범위

| 파일 | 변경 유형 | 요약 |
|------|-----------|------|
| `revdoc/gate.py` | 삭제 + 축소 | 추적성 정규식·체크·피드백 ~30줄 삭제, min_length 기본값 800 → 500 |
| `revdoc/prompts/reverse_doc_v1.md` | 이름 변경 + 내용 완화 | → `reverse_doc.md`. "Rule/Condition/Evidence 삼각" 요구 제거, 최소 길이 800 → 500 |
| `job_store.py` | 경로 수정 + 로직 추가 | `_load_reverse_doc_prompt()` 파일명 수정, 신규 `ensure_latest_prompt()` 헬퍼, `seed_prompts()`에서 reverse_doc만 이 신규 헬퍼 사용 |
| `tests/test_revdoc_gate.py` | 삭제 + 수정 | 추적성 테스트 2개 삭제, 나머지는 길이 기준·assertion 조정 |
| `tests/test_job_store.py` (또는 `tests/test_prompt_store.py`) | 추가 | `ensure_latest_prompt` 동작 검증 테스트 |
| `tests/test_revdoc_generator.py`, `tests/test_revdoc_endpoint.py` | 확인 | 기존 테스트가 단순화된 gate 하에서 여전히 의도대로 pass/fail하는지 확인 (필요 시 fixture 조정) |
| `CLAUDE.md`, `TODO.md` | 업데이트 | 진행 기록 반영 |

**변경 외 파일**: `revdoc/generator.py` (인터페이스 불변), `app.py` (lifespan 변화 없음), 다른 extractor·router·worker 무관.

---

## 4. 설계

### 4.1 게이트 (`revdoc/gate.py`)

현행 3단계 우선순위 `sections > traceability > length`를 **2단계 `sections > length`**로 축소.

#### 4.1.1 삭제 항목

```python
# 전부 제거
_RULE_RE = re.compile(r"Rule\s*[:：]")
_COND_RE = re.compile(r"Condition\s*[:：]")
_EVID_RE = re.compile(r"Evidence\s*[:：]")
```

`check()` 내부 "2. Traceability triangle" 블록(약 30줄: `has_rule`/`has_cond`/`has_evid` 계산, `missing_pieces` 판정, 관련 `GateVerdict` 반환) 전체 삭제.

#### 4.1.2 조정 항목

- `RevdocGate.__init__(min_length: int = 500)` — 기본값 800 → 500.
- `GateVerdict.details` 키 구성 변화:
  - pass: `{"missing_sections": [], "length": int}` (기존 `traceability` 키 제거)
  - 섹션 실패: `{"missing_sections": [...]}` (기존과 동일 형태, 키 셋 동일)
  - 길이 실패: `{"missing_sections": [], "length": int}`

#### 4.1.3 유지 항목

- `REQUIRED_SECTIONS` 7개 헤더 리스트 (`업무목적`, `처리흐름`, `입력/출력`, `규칙/예외`, `근거`, `추적성`, `관련업무`).
  - 추적성 섹션 **제목은 유지** — 내용만 자유 서술로 완화(§4.2).
  - 이유: LightRAG 청크 예측성, 사람이 읽기 쉬움, LLM의 구조 탈선 최소 방지.
- `GateVerdict` 데이터클래스 (passed/details/reason/feedback 필드 동일).
- Retry feedback 문자열 포맷 (섹션 누락·길이 부족만 남음).
- 동기/무상태 계약, 외부 의존성 0 (C1·C6 유지).

### 4.2 프롬프트 파일

#### 4.2.1 파일 이름

`revdoc/prompts/reverse_doc_v1.md` → `revdoc/prompts/reverse_doc.md`

이유: 버전 관리는 DB(`forge_prompts.version`)가 수행. 파일명에 v1/v2를 박으면 단순화 취지에 반함. `git mv`로 이름 변경.

#### 4.2.2 내용 변경

**추적성 섹션(## 추적성) 문구**:

```
(현행)
- **Rule**: 업무 규칙명 (예: R-001 고객 등급 산출)
- **Condition**: 코드상의 조건 (예: IF total_amount > 1000 AND tier = 'GOLD')
- **Evidence**: 코드 위치 + 주석 (예: customer_tier.py:45, "High value customer upgrade")

삼각이 세 항목 모두 채워져야 한다. 하나라도 빠지면 게이트 실패로 간주된다.
```

**→ 변경 후**:

```
코드와 업무 규칙의 연결을 자유롭게 서술한다.
어떤 로직이 어떤 업무 규칙을 구현했는지, 근거를 어디서 확인할 수 있는지 등을 설명할 수 있다.
형식(목록/표/서술)은 자유.
```

**## 제약 섹션**:

- 기존 "추적성은 Rule/Condition/Evidence 삼각으로 최소 1건." 행 삭제.
- "전체 길이 최소 800자." → "전체 길이 최소 500자."

**유지**:
- 7섹션 정확 헤더 사용 요구 — 게이트가 계속 검사함.
- "TBD 금지", "추측 금지", "빈 섹션 금지" 등 일반 품질 제약.

### 4.3 배포 로직 (`job_store.py`)

#### 4.3.1 문제

현행 `seed_if_empty`는 "DB가 비어있을 때만" 시드. 이미 v1이 시드된 기존 배포에서는 파일 내용을 바꿔도 **DB가 절대 갱신되지 않음**. 배포마다 수동 `POST /prompts/reverse_doc`을 요구하는 것은 운영 부담.

#### 4.3.2 신규 헬퍼

```python
def _normalize_prompt_text(text: str) -> str:
    """줄바꿈·인코딩 차이를 정규화하여 비교 안정성 확보.

    - CRLF → LF (Windows git autocrlf 대응)
    - 파일 끝 trailing whitespace 제거 (editor save 차이 대응)
    두 정규화를 모두 적용한 결과로 비교.
    """
    return text.replace("\r\n", "\n").rstrip()


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
```

구현 위치: `job_store.py` 모듈 수준, `seed_prompts` 바로 위.

**비교 전 정규화 — 왜**: Forge는 Windows 개발 + Linux Docker 배포 혼재 환경. `core.autocrlf`
설정이 다른 환경에서 시드된 후 부팅하면 CRLF/LF 차이로 "텍스트 다름"으로 오판 → 재부팅마다
새 버전 생성. 100번 부팅 = `forge_prompts` 100행 noise. 정규화는 이 노이즈 원천 차단.

#### 4.3.3 seed_prompts 변경

```python
async def seed_prompts(store) -> None:
    """reverse_doc 프롬프트를 최신 파일 내용으로 보장.

    설계 주의 — 시드 메커니즘 병행:
    * `reverse_doc`: `ensure_latest_prompt` 사용 — 내용 튜닝이 잦고 파일이 SSoT.
    * `semantic_batch`, `meta_extract`: 호출처(`app.py` lifespan)에서 `seed_if_empty`
      사용 — 초기 시드 후 변경은 Admin API(`POST /prompts`)로 관리. 자동 덮어쓰기가
      오히려 운영 리스크.

    두 패턴이 공존하는 것은 의도된 설계. 통합은 스코프 밖(§2.2, §9 참조).
    """
    reverse_doc_text = _load_reverse_doc_prompt()
    await ensure_latest_prompt(store, "reverse_doc", reverse_doc_text)
```

`semantic_batch`, `meta_extract`는 `app.py` lifespan에서 `seed_if_empty`로 호출되어 그대로 유지 (이 스펙 스코프 밖). 필요 시 후속 작업에서 일괄 전환.

#### 4.3.4 파일 로더

```python
def _load_reverse_doc_prompt() -> str:
    path = os.path.join(..., "revdoc", "prompts", "reverse_doc.md")  # v1 접미사 삭제
    ...
```

누락 시 `RuntimeError` 발생은 현행 유지(배포 누락 감지).

### 4.4 데이터 플로우

```
[startup: app.py lifespan]
  ├─ init DB pool
  ├─ seed_prompts(store)
  │    └─ ensure_latest_prompt(store, "reverse_doc", load_file("reverse_doc.md"))
  │         ├─ DB active 없음              → create_version(v1)
  │         ├─ DB active.text == 파일 텍스트 → no-op
  │         └─ DB active.text ≠ 파일 텍스트  → create_version(v+1, auto-active)
  │
[request: POST /reverse-doc]
  └─ ReverseDocGenerator.generate(source_code, file_name)
       ├─ PromptStore.get_active("reverse_doc") → 최신 버전 가져옴
       ├─ VLMClient.process_text(code, prompt)
       ├─ RevdocGate.check(md) ← 섹션 + 길이 2단계만
       │    ├─ pass → Refiner.refine → return RevdocResult
       │    └─ fail → feedback 피드백 append → max_retries 만큼 루프
       └─ retries 소진 → 마지막 generation 반환 (현행과 동일)
```

게이트 내부 로직이 줄어든 것 외에는 generator·VLM·refiner 호출 구조 변화 없음. 기존 `RevdocResult` 필드 호환 유지.

### 4.5 에러 처리

| 시나리오 | 동작 |
|----------|------|
| `reverse_doc.md` 파일 누락 | startup 시 `RuntimeError` → app 부팅 실패 (현행 동작 유지) |
| DB 풀 초기화 실패 | lifespan 단계에서 기존대로 실패 전파 |
| `ensure_latest_prompt` write 실패(DB 장애 등) | 예외를 lifespan으로 전파 → 부팅 중단 (프롬프트 배포 무결성 우선) |
| LLM 호출 실패 | `ReverseDocGenerator` 레벨에서 기존 retry 로직 재사용 — 이 스펙에서 변경 없음 |
| 게이트 false-negative (섹션 누락이라고 잘못 판정) | 기존 gate 동작과 동일 — 섹션 검사 로직 자체는 변경 없음 |

**운영 환경 전제**:
- 현 시점 Forge는 **단일 uvicorn 워커** 운영(Docker compose 기준). `ensure_latest_prompt`는
  이 전제 하에서 race-free 동작.
- 멀티 워커 전환 시 두 워커가 동시 startup → 같은 텍스트로 버전 중복 생성 가능
  (DB 유니크 제약은 `is_active=TRUE`에만 걸려 중복 자체는 허용). 기능적 장애는 없으나
  버전 번호 노이즈 발생.
- 멀티 워커 도입 시 후속 작업으로 `pg_advisory_lock(hashtext('forge_prompts:seed'))`을
  `ensure_latest_prompt` 진입부에 추가해 직렬화 권장 (§9 참조).

### 4.6 하위 호환성

- `RevdocGate` 생성자 시그니처: `__init__(min_length=500)`. 기본값 변경 외 시그니처 동일. 호출자가 명시적으로 `min_length=800`을 넘기면 여전히 그 값으로 동작.
- `GateVerdict.details` 딕셔너리: `traceability` 키가 사라짐. 현재 코드베이스에서 이 키를 소비하는 곳은 테스트 외에 없음(`grep`으로 확인 예정). 테스트 수정으로 커버.
- 외부 API(`POST /reverse-doc`) 응답 스키마: 변화 없음.
- DB 스키마: 변화 없음 (`forge_prompts` 테이블 그대로).

---

## 5. 테스트 계획

### 5.1 삭제

`tests/test_revdoc_gate.py`:
- `test_gate_fail_traceability_missing_rule` — 삼각 검사 자체가 없어짐.
- `test_gate_accepts_korean_fullwidth_colon` — 같은 이유.

### 5.2 수정

`tests/test_revdoc_gate.py`:

| 테스트 | 수정 사항 |
|--------|-----------|
| `test_gate_pass_minimal` | `details["traceability"]` assertion 제거. `length` assertion 유지. |
| `test_gate_fail_length_under_800` | → `test_gate_fail_length_under_500`로 이름/값 변경. |
| `test_gate_fail_priority_order` | 우선순위 2단계로 축소(sections > length). "traceability 없음" 변형 삭제. |
| `test_gate_feedback_populated_on_failure` | 3가지 실패 케이스 중 triangle 케이스 삭제 → 2가지(섹션, 길이)만. |
| `test_gate_details_always_populated` | `traceability` 키 관련 contract 제거. 3가지 상태(pass/section-fail/length-fail)로 축소. |
| `test_gate_custom_min_length` | 동작은 불변(min_length 커스텀 기능 유지). 가독성 위해 인라인 MD의 추적성 섹션 내용만 `"Rule: x\nCondition: y\nEvidence: z"`에서 자유 서술 한 줄로 변경. |
| `test_gate_required_sections_constant_matches_prompt` | 변경 없음. |
| `test_gate_verdict_is_dataclass_shape` | 변경 없음. |
| `_valid_md()` 헬퍼 | 추적성 섹션 내용을 자유 서술(`"이 코드는 고객 등급 산출 로직을 구현한다."`)로 변경. Rule/Condition/Evidence bullet 제거. |

### 5.3 추가

**`tests/test_prompt_store.py`** (기존 파일, 확장) — `ensure_latest_prompt` 6가지 시나리오:

**기본 동작 3건**:
1. `test_ensure_latest_prompt_creates_when_empty`: 비어있는 store에 호출 → v1 생성.
2. `test_ensure_latest_prompt_noop_when_same`: 동일 텍스트로 두 번째 호출 → 여전히 버전 1, write 발생 X.
3. `test_ensure_latest_prompt_upgrades_when_different`: 다른 텍스트로 호출 → v2 생성, v2가 active, v1은 비활성.

**정규화 엣지 케이스 3건** (§1.2·§4.3.2 반영):
4. `test_ensure_latest_prompt_ignores_trailing_newline`: DB에 `"text"`, 파일이 `"text\n"` → no-op (정규화 후 동일).
5. `test_ensure_latest_prompt_ignores_crlf_diff`: DB에 `"a\nb"`, 파일이 `"a\r\nb"` → no-op (Windows autocrlf 대응).
6. `test_ensure_latest_prompt_detects_real_content_change`: DB에 `"hello"`, 파일이 `"hello world"` → 새 버전 생성(정규화가 실제 변화를 가리지 않음).

`InMemoryPromptStore` 기반 검증. `PostgresPromptStore` 통합 테스트는 기존 infra·CI 범위 외.

### 5.4 회귀 — fixture 재구성 (필수 task)

`tests/test_revdoc_generator.py`, `tests/test_revdoc_endpoint.py`:

**왜 fixture 재구성이 필수인가**: 기존 fixture가 만드는 mock LLM 응답은 v1 gate 통과용으로
`Rule:/Condition:/Evidence:` 삼각을 포함하고 있을 확률 높음. 단순화 후에는:
- **pass fixture**: 추적성 삼각 있든 없든 상관없음(게이트 체크 대상 아님). 그러나 길이가 ≥500자인지 필수 확인.
- **fail fixture**: 기존에 "Rule 누락"으로 실패 유도했다면, 새 gate는 그걸로 실패시키지 않음 → 반드시 **섹션 누락** 또는 **<500자**로 fail 유도 재구성.

**구현 단계 checklist** (플랜 task로 승격):
- [ ] `test_revdoc_generator.py`의 mock 응답 문자열 검토 → 각 fixture가 의도대로 pass/fail하는지 확인
- [ ] pass fixture 최소 1개: 새 gate 기준(7섹션 + ≥500자) 충족하는 MD
- [ ] fail fixture 최소 1개: 섹션 누락으로 fail → retry 경로 트리거 확인
- [ ] fail fixture 최소 1개 (선택): 길이 부족으로 fail → retry 경로 트리거 확인
- [ ] `test_revdoc_endpoint.py` 동일 점검

확인만으로 끝나면 안 되는 이유: "mock이 여전히 같은 응답을 줘도 새 gate에선 다른 판정"이
날 수 있어서 pass/fail 결과 자체가 바뀌고 테스트가 무효해질 수 있음.

### 5.5 실측

로컬 `uvicorn app:app --port 8003` + OpenRouter 실제 LLM 기반 E2E 테스트.

**테스트 샘플**:
- **주샘플**: `discount.pkb` (2026-04-23 3-attempts-fail 재현 건) — 1-attempt pass 여부
- **회귀 샘플 2-3건**: 이전 v1에서 gate pass했던 역문서 생성 건 → 단순화된 gate로도 pass하는지 확인.
  샘플 출처: 2026-04-23 라이브 테스트 시 성공한 `/reverse-doc` 결과물(로그/DB의 `attempts=1 passed=true` 케이스)

**측정 항목**:
- attempts 횟수 (기대: 실패 샘플 3→1, 회귀 샘플 1 유지)
- 생성된 MD 길이 (500자 이상 여부)
- 수동 품질 체크 (§5.6 참조)

### 5.6 완료 기준

**정량 기준**:
- `python -m pytest tests/ -v` 통과 — 약 **273개** (269 기존 - 2 삭제 + 6 신규 추가[기본 3 + 정규화 3])
- `discount.pkb` 실측 **1-attempt pass**
- 회귀 샘플 2-3건 모두 **gate 통과 유지**
- `/health` 200 OK

**정성 기준 (수동 품질 체크)**:
- 실측으로 생성된 각 MD에 대해 reviewer가 육안 확인:
  - 7개 섹션 각각에 **최소 1문단(2-3문장 이상)의 의미 있는 서술** 존재
  - "TBD", "추후 작성", "N/A" 등 placeholder 금지 (프롬프트에 명시)
  - 섹션 제목은 있지만 본문이 빈약(1줄 이하)인 경우 → 프롬프트 추가 튜닝 필요성 기록
- 이 체크는 **구현 완료 판정의 필수 게이트**. 자동화 않고 reviewer 판단에 맡김 (초반 적용 단계의 현실적 타협).

**실패 시 대응**:
- 정량 실패: 코드 수정 루프
- 정성 실패(형식은 통과하지만 내용 부실): 프롬프트 §4.2.2의 "제약" 섹션 강화(각 섹션 최소 분량 권고 등) → 재실측. 3회 이상 반복 시 스펙 §2.2 비목표를 재검토(품질 자동 체크 도입 여부)

---

## 6. 롤아웃 절차

1. 브랜치 유지: `feature/v3-lightrag-extension`.
2. 코드 변경:
   - `git mv revdoc/prompts/reverse_doc_v1.md revdoc/prompts/reverse_doc.md`
   - 프롬프트 내용 수정.
   - `revdoc/gate.py` 단순화.
   - `job_store.py`: 경로 수정 + `ensure_latest_prompt` 추가 + `seed_prompts` 갱신.
   - 테스트 수정.
3. 로컬 전체 테스트 (`python -m pytest tests/ -v`).
4. 로컬 서버 기동 + 실제 샘플 호출로 게이트 동작 실측.
5. Commit (conventional commit 스타일: `refactor(revdoc): gate 추적성 검사 제거 + 프롬프트 완화`).
6. TODO.md·메모리 업데이트.
7. PR/머지는 별도 판단 (본 스펙 밖).

**롤백 계획**: git revert. 파일명 변경은 `git mv`로 기록되어 있으므로 복원 단순. DB의 버전 레코드는 revert 후에도 남지만, 구 버전이 active로 복귀하지 않으므로 운영자가 `POST /prompts/reverse_doc/{v}/activate`로 수동 선택.

---

## 7. 리스크 / 트레이드오프

| 리스크 | 판단 |
|--------|------|
| 추적성 검사 제거로 LLM이 느슨한 문서 생성 | 수용 — 초반 적용 단계에서는 "도메인 설명" 자체가 성공 기준이라고 합의. 진짜 필요 시점에 다시 엄격화 가능 (git에 구 로직 남아있음). |
| `ensure_latest_prompt`의 SSoT가 파일 → DB 단방향 | 의도한 동작. 운영자가 `POST /prompts`로 DB만 수정하면 다음 startup에 덮어써짐. 운영 절차상 파일 먼저 수정하도록 문서화(DEPLOYMENT.md 보강은 후속). |
| 삭제 테스트가 실제로 가치 있던 경우 | 현재 케이스는 "존재하지 않는 검사"를 검증하는 테스트이므로 삭제가 타당. |
| 길이 기준 500으로 낮춰서 품질 저하 | 실측으로 검증. `discount.pkb` 케이스에서 생성된 MD가 500-800 사이에서도 도메인 설명이 충분하면 OK. 500도 지나치면 700 정도로 재조정 여지. |

---

## 8. 결정 사항 (확정)

| 항목 | 결정 | 대안 | 이유 |
|------|------|------|------|
| 게이트 단순화 수준 | Level 2 (삼각 검사 제거, 섹션+길이만) | Level 1 (정규식만 수정), Level 3 (테이블 강제) | 초반 적용 단계, 진짜 추적성은 RAG 수준 필요 |
| 프롬프트 파일 이름 | `reverse_doc.md` | `reverse_doc_v1.md` 유지, `reverse_doc_v2.md` 추가 | 버전은 DB가 관리, 파일명 버전 접미사 불필요 |
| 프롬프트 업그레이드 메커니즘 | 자동 (startup 시 파일 내용 비교 후 신규 버전 생성) | 수동 `POST /prompts` 호출 | 운영 부담 최소 |
| 섹션 헤더 체크 유지 | 유지 | 제거 | LightRAG 청크 예측성, 사람 가독성, 최소 구조 |
| 길이 기준 | 500 | 800(현행), 제거 | 자유 서술 허용하면서 "완전히 망가진 답"은 여전히 걸러짐 |
| 다른 프롬프트 업그레이드 | 이번 스코프 밖 | 일괄 전환 | 스코프 작게 유지, 필요 시 후속 |

---

## 9. 추후 작업 (스코프 밖)

- `semantic_batch`, `meta_extract` 프롬프트도 `ensure_latest_prompt`로 통합 (후속, DRY).
- `DEPLOYMENT.md`에 "프롬프트 배포는 파일 수정 후 Forge 재기동" 절차 추가.
- **멀티 워커 advisory lock**: `pg_advisory_lock(hashtext('forge_prompts:seed'))`을
  `ensure_latest_prompt` 진입부에 추가. 프로덕션 멀티 워커 운영 시점에 필요 (§4.5 참조).
- **LLM 출력 품질 자동 게이트**: 현재 수동 체크(§5.6)를 자동화. LLM judge 또는 섹션별
  min-body 체크. 실사용 피드백 축적 후 도입 판단.
- RAG 통합 역문서 (`memory/project_reverse_doc_rag_backlog.md`).
- 진짜 추적성 검증 (파일:라인이 실재 코드와 매칭되는지 AST 수준 확인) — 컴플라이언스 요구 구체화 시.

---

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | not required (단순화 스코프, 사용자 판단으로 전략 검토 불필요) |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | — | skipped (사용자 요청: eng-review만) |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | CLEAR | 7 findings (P1×2, P2×5, P3×1), 전부 반영 완료 |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | n/a (UI 요소 없음) |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | — | n/a (내부 로직) |

- **VERDICT**: ENG CLEARED — writing-plans로 이동 가능
- **UNRESOLVED**: 0
- **CRITICAL GAPS CLOSED**: 2건 (silent quality degradation → §5.6 수동 체크 / version spam → §4.3.2 정규화)
