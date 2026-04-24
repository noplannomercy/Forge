# Forge — 개발 이력

프로젝트 전체 개발 히스토리. 스펙 → 구현 → 검증 순서로 기록.
상세 스펙/플랜은 `docs/superpowers/` 참조.

---

## v3.3 — revdoc Gate 단순화 (2026-04-24)

**목표:** Gate 오탐(false negative)을 줄이고, 프롬프트를 코드 없이 업그레이드할 수 있게.

| 변경 | 내용 |
|------|------|
| 추적성 정규식 제거 | "이 코드는...구현한다" 패턴 강제 → 자유 서술 허용 |
| min_length 완화 | 800 → 500 chars |
| `ensure_latest_prompt` 도입 | 서버 기동 시 파일과 DB 내용 비교 → 다르면 자동 새 버전 생성 |
| 프롬프트 파일 통합 | `reverse_doc_v1.md` → `reverse_doc.md` (버전 번호 파일명 제거) |
| Gate 2단계로 명확화 | 섹션 체크 → 길이 체크 (우선순위 순) |

관련 문서:
- 스펙: `docs/superpowers/specs/2026-04-24-revdoc-gate-simplification-design.md`
- 플랜: `docs/superpowers/plans/2026-04-24-revdoc-gate-simplification.md`

---

## v3.2 — LightRAG Extension (2026-04-22 ~ 23)

**목표:** Forge 변환 결과를 LightRAG 그래프 RAG 시스템에 자동 인제스트.

| 기능 | 상세 |
|------|------|
| `CALLBACK_FIELD_MAP` | callback payload 필드명 consumer별 rename (JSON 문자열) |
| `CALLBACK_KEEP_UNMAPPED` | rename 안 된 필드 제거 옵션 (LightRAG 연동 시 `false`) |
| HWPX → docling bridge | LibreOffice headless로 DOCX 변환 → docling-serve 전달 |
| `DoclingLogStore` | docling-serve 호출 이력 DB 저장 (InMemory + Postgres) |
| `POST /reverse-doc` | 소스코드 → 역문서 생성 (비동기 job 기반) |
| `POST /refine` | Markdown 6단계 정제 (동기 응답) |

VPS Hostinger(193.168.195.222)에서 LightRAG(:9621) + docling-serve(:5001) 구동 확인.

```
Forge /convert + callback_url → CALLBACK_FIELD_MAP rename →
LightRAG /documents/text → 그래프 인덱싱
```

관련 문서:
- 스펙: `docs/superpowers/specs/2026-04-22-forge-lightrag-extension-design.md`
- SRS: `docs/SRS-v3-lightrag.md`

---

## v3.1 — /reverse-doc + /refine (2026-04-11 ~ 22)

**목표:** 소스 코드로부터 업무 명세 문서(MD)를 자동 생성.

| 컴포넌트 | 파일 | 역할 |
|----------|------|------|
| Refine 6단계 | `refine/stages.py` | 인코딩·줄바꿈·특수문자·frontmatter·codefence·추적성 |
| Validator/Gate | `refine/validator.py` | refine 결과 품질 게이트 |
| Refiner | `refine/refiner.py` | 6단계 + validator 오케스트레이션 |
| RevdocGate | `revdoc/gate.py` | 역문서 품질 게이트 (7섹션 + 길이) |
| ReverseDocGenerator | `revdoc/generator.py` | 역문서 생성 + gate + refine (최대 3회) |
| `POST /refine` | `app.py` | 동기 MD 정제 엔드포인트 |
| `POST /reverse-doc` | `app.py` | 비동기 역문서 생성 엔드포인트 |

역문서 7섹션: 업무목적 · 처리흐름 · 입력/출력 · 규칙/예외 · 근거 · 추적성 · 관련업무

---

## v3.0 — DB + 메타 추출 + 관리 API + 프롬프트 외부화 + callback (2026-04-07 ~ 09)

### DB + 메타 추출

| 기능 | 상세 |
|------|------|
| PostgreSQL 연동 | asyncpg 기반 `PostgresJobStore`, `VLMLogStore` |
| InMemory fallback | `DATABASE_URL` 미설정 시 재시작 전까지 유지 |
| LLM 메타 자동 추출 | 변환 완료 후 제목·분류·키워드·요약 자동 추출 |
| `forge_prompts` 테이블 | 프롬프트 버전 관리 (is_active 기반 활성 버전) |

### 관리 API

```
GET  /jobs              Job 목록 (필터: status, source_format)
GET  /jobs/{id}         Job 단건 상세
PATCH /jobs/{id}/meta   메타 수동 보정
POST  /jobs/{id}/retry  메타 재추출
DELETE /jobs/{id}       Soft delete
GET  /stats/daily       일별 변환 통계
GET  /stats/cost        VLM 비용 집계
GET  /stats/models      모델별 사용량
```

인증: `X-Forge-Key` 헤더 (`FORGE_API_KEY` 환경변수)

### 프롬프트 외부화

```
GET  /prompts                     전체 버전 이력
GET  /prompts/{type}/active       활성 프롬프트 조회
POST /prompts                     새 버전 등록 (기존 비활성화)
```

코드 배포 없이 VLM 프롬프트(semantic, meta_extract, reverse_doc) 교체 가능.

### callback URL

```
/convert?callback_url=http://cortex/v1/ingest
```

변환 완료 후 결과를 외부 URL로 POST. Cortex/LightRAG 자동 파이프라인.

### HWPX extractor

HWPX ZIP+XML 파싱으로 `hp:t` 텍스트+표 추출 → Markdown.

관련 문서:
- `docs/superpowers/specs/2026-04-07-forge-db-meta-design.md`
- `docs/superpowers/specs/2026-04-08-forge-admin-api-design.md`
- `docs/superpowers/specs/2026-04-09-forge-prompt-externalize-design.md`
- `docs/superpowers/specs/2026-04-09-forge-callback-design.md`
- `docs/superpowers/specs/2026-04-09-forge-hwpx-extractor-design.md`

---

## v2.0 — VLM semantic 배치 처리 (2026-04-07)

**목표:** PPTX, 스캔 PDF, 이미지를 VLM으로 의미 재구성.

| 기능 | 상세 |
|------|------|
| LibreOffice headless | PPTX → PDF 변환 (`soffice --headless`) |
| PDF → 이미지 | pypdfium2로 페이지별 PNG 변환 |
| semantic 배치 VLM | `VLM_BATCH_SIZE` 페이지 묶음으로 VLM 호출 |
| Semaphore 동시성 | `VLM_CONCURRENCY`로 병렬 호출 제한 |
| 3회 retry | 지수 백오프 (1s, 2s, 4s) |
| 부분 실패 허용 | 실패 배치 = placeholder, 성공 배치 보존 |
| `?route=vlm` | 강제 VLM 경로 지정 |
| Docker | LibreOffice 포함 컨테이너 이미지 |

관련 문서:
- `docs/superpowers/specs/2026-04-07-forge-semantic-vlm-design.md`
- `docs/superpowers/plans/2026-04-07-forge-semantic-vlm.md`

---

## v1.0 — 문서 변환 기반 (2026-04-07)

**목표:** PDF, DOCX, PPTX, XLSX, 이미지를 Markdown으로 변환하는 비동기 REST 서비스.

| 기능 | 상세 |
|------|------|
| `POST /convert` | 파일 업로드 → job_id 즉시 반환 (비동기) |
| `GET /result/{id}` | 변환 결과 조회 (status + text + quality) |
| `POST /batch` | 다중 파일 배치 변환 |
| `GET /health` | 헬스체크 |
| InMemoryJobStore | 기본 스토리지 (재시작 전까지 유지) |
| extractors | DOCX·XLSX·HWPX·PDF·이미지 추출기 |
| `?route=` | extract / vlm 경로 강제 지정 |
| 100MB 파일 제한 | MAX_FILE_SIZE 초과 시 413 |

관련 문서:
- `docs/superpowers/specs/2026-04-07-forge-converter-design.md`
- `docs/superpowers/plans/2026-04-07-forge-converter.md`

---

## 테스트 이력

| 날짜 | 테스트 수 | 비고 |
|------|-----------|------|
| 2026-04-07 | 초기 | v1 기본 기능 |
| 2026-04-08 | 수동 15/15 | v2 VLM 포함 |
| 2026-04-09 | 145+ | v3 DB+메타+관리 API |
| 2026-04-24 | 275+ | v3.3 revdoc gate 단순화 후 회귀 |

LibreOffice 미설치 환경에서 `test_office.py` 2건 실패는 정상.

---

## 실전 검증 이력

| 날짜 | 내용 |
|------|------|
| 2026-04-09 | Cortex 연계: 거버 제안.docx + 현대케피코.docx → 25 chunks / 222 entities / 210 relations |
| 2026-04-09 | 도커 통합 테스트: infra + cortex + forge compose, hc-rag-network, 서비스명 통신 |
| 2026-04-23 | LightRAG 연계 실전: /convert (PDF) + /reverse-doc (PKB) → LightRAG 인제스트 확인 |
| 2026-04-24 | CALLBACK_FIELD_MAP 동작 확인: content→text, file_name→file_source rename 검증 |
