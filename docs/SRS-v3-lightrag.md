# SRS: Forge — LightRAG Extension (v3)

> 기존 `docs/SRS.md` (v2)의 **확장**. v2 요구사항은 모두 유지되며, Cortex 기본 경로는 영향 없음 (C1 제약 준수).

---

## 1. 배경

LightRAG PoC 검증 완료 (Track A: PG16 + pgvector + AGE1.6.0 마이그레이션 성공, 18 docs 재인덱싱, R-1~R-5 골든셋 평균 9.0/10). 이에 따라 기존 Cortex를 LightRAG가 대체 consumer로 전환.

Forge는 **consumer-agnostic 변환기** 원칙을 유지하되, 다음 세 가지 신규 기능이 필요:
1. **Docling 통합** — 기존 PDF 경로의 한국어·표 품질을 프로덕션 수준으로 끌어올림
2. **`/refine`** — 이미 텍스트·MD인 입력의 6단계 정제 파이프라인
3. **`/reverse-doc`** — PL/SQL 등 코드 → 자연어 업무 문서 생성

### 1.1 선행 조사 여정 (Docling 채택 근거)

| 단계 | 대안 | 실측 결과 | 판정 |
|---|---|---|---|
| 1 | RAG-Anything + MinerU | VPS CPU 페이지당 186초, GPU 필수 | ❌ 비채용 |
| 2 | MarkItDown | 영문 표 깨짐, 한국어 2단 컬럼 Reading order 붕괴, 노이즈 반복 | ❌ 비채용 |
| 3 | **Docling (IBM)** | 영문 Table 2·3 완벽 MD 표, 한국어 한국은행 금융안정보고서 10p 48.8s에 완벽 구조화 | ✅ **채용** |

실측 데이터는 `C:/workspace/lightrag/track_e_rag_anything_eval.md`에 정리 (예정).

---

## 2. 목표 / 비목표

### 2.1 목표

- Forge가 LightRAG consumer를 지원 (Cortex C1 제약 유지)
- Forge PDF 경로의 한국어·표 품질 향상 (Docling)
- MD 입력의 6단계 정제 파이프라인 제공
- PL/SQL 코드 → 업무 Markdown 역문서 생성
- 기존 Forge 비동기 Job / PromptStore / Admin API 패턴 100% 재사용

### 2.2 비목표 (v3 범위 제외)

- 기존 Cortex 연계 제거·변경 (C1 준수)
- GPU 의존 파서 추가 (MinerU·Marker 등)
- MD 이외 포맷의 `/refine` 입력 (텍스트만)
- Docling 실패 시 AI 기반 fallback (pypdfium2 fallback만)
- SME 피드백 루프 UI (Phase 4 별도 SRS)

---

## 3. 기능 요구사항

### 3.1 DOCLING — Docling extractor 통합

| ID | 요구사항 |
|---|---|
| DOCLING-01 | `docling` 패키지를 requirements.txt에 추가한다 |
| DOCLING-02 | `extractors/docling.py` 신설, 기존 S4 시그니처(`async def extract(file_bytes, file_name) -> ConvertResult`) 준수 |
| DOCLING-03 | 첫 호출 시 Docling IBM 모델(~506MB) 자동 다운로드를 허용한다 |
| DOCLING-04 | CPU 추론 모드를 기본으로 사용한다 (`accelerator_options.device='cpu'`) |
| DOCLING-05 | 출력 Markdown에서 표를 `\|...\|` 형식으로 보존한다 |
| DOCLING-06 | 이미지는 `<!-- image -->` placeholder로 남긴다 (VLM 호출 없음) |
| DOCLING-07 | OOM·예외 발생 시 기존 pypdfium2 경로로 fallback하고 quality.fallback=true 기록 |
| DOCLING-08 | Docling 변환 중 `forge_vlm_logs`와 유사한 구조의 `forge_docling_logs`에 페이지 수·소요 시간 기록 |

### 3.2 ROUTE — 라우팅 확장

| ID | 요구사항 |
|---|---|
| ROUTE-06 | PDF의 "추출 경로"(ROUTE-04)는 기본적으로 Docling extractor로 처리한다 |
| ROUTE-07 | 스캔 PDF(chars_per_mb < 100) 기준은 유지 — VLM 경로 |
| ROUTE-08 | `?route=vlm\|extract\|docling` 쿼리 파라미터로 강제 지정 가능 |
| ROUTE-09 | HWPX는 LibreOffice → DOCX 변환 후 Docling extractor로 처리한다 |

### 3.3 REFINE — MD 정제 엔드포인트

| ID | 요구사항 |
|---|---|
| REFINE-01 | `POST /refine` — multipart/form-data 또는 raw text body로 텍스트·MD를 받는다 |
| REFINE-02 | 6단계 정규화 파이프라인: (1) 인코딩 (cp949/euc-kr → UTF-8), (2) 개행 복원 (`\n` 리터럴 → 실제 개행), (3) 특수문자 (`~`, `·`, 전/반각), (4) frontmatter 스트립 (YAML 블록), (5) code fence (옵셔널 스트립), (6) Traceability 문장화 (`↔` → 문장) |
| REFINE-03 | 각 단계별 적용 여부와 변경 라인 수·바이트 수를 리포트로 반환한다 |
| REFINE-04 | 검증 규칙: UTF-8 디코드 성공, 개행 ≥ 1, 한글 비율 ≥ 임계(기본 0.1), 최소 길이 ≥ 임계(기본 100). 위반 시 `quality.gate='fail'` + 사유 명시 |
| REFINE-05 | 기존 Forge Job 패턴(C4 `_safe_process`) 준수, 비동기·동기 모두 지원 |
| REFINE-06 | 정제 규칙은 `forge_refine_rules` 테이블(`forge_prompts` 패턴 모방)에서 버전 관리한다 |
| REFINE-07 | 동기 응답은 1 MB MD 기준 100 ms 이내 |

### 3.4 REVDOC — 역문서 생성 엔드포인트

| ID | 요구사항 |
|---|---|
| REVDOC-01 | `POST /reverse-doc` — 코드 파일(.pkb/.pks/.prc/.fnc/.trg 등)을 받아 Markdown 업무 문서로 반환한다 |
| REVDOC-02 | 프롬프트는 `forge_prompts` 테이블(type='reverse_doc')로 버전 관리 |
| REVDOC-03 | 기본 프롬프트는 `C:/workspace/day1-plsql-parsing/src/prompts/prompt_A_doc_gen.md` 기반 7섹션 템플릿 (업무목적 / 처리흐름 / 입력출력 / 규칙예외 / 근거Evidence / 추적성Traceability / 관련업무) |
| REVDOC-04 | LLM 호출은 기존 VLM 클라이언트 패턴(S1 Semaphore + S2 3회 retry 지수백오프) 재사용 |
| REVDOC-05 | 품질 게이트: 7개 섹션 헤더 존재, Traceability 최소 1개 삼각 (Rule·Condition·Evidence 모두), 길이 ≥ 임계 |
| REVDOC-06 | 게이트 실패 시 최대 2회 자동 재시도 (프롬프트 피드백 포함), 이후 `quality.gate='fail'` |
| REVDOC-07 | `prompt_version`을 Job 메타에 기록한다 |
| REVDOC-08 | 출력 전 자동으로 `/refine` 파이프라인을 거쳐 LightRAG 투입 품질로 정규화한다 |

### 3.5 CALLBACK — LightRAG consumer 연계

| ID | 요구사항 |
|---|---|
| CALLBACK-01 | 기존 `?callback_url=` 파라미터를 consumer-agnostic으로 유지한다 (C1 준수 — LightRAG 전용 코드 금지) |
| CALLBACK-02 | LightRAG의 `POST /documents/upload` 호환 payload로 호출 가능해야 한다 |
| CALLBACK-03 | callback payload는 기존 스펙(`pre_converted=true`, `X-API-Key`) 그대로. LightRAG 전용 필드를 강제하지 않는다 |
| CALLBACK-04 | callback 실패 시 기존 재시도 정책 준수 |
| CALLBACK-05 | 환경변수 문서화: `CALLBACK_API_KEY`, 예시 URL 추가 (`docs/CORTEX-INTEGRATION.md`에 LightRAG 예제 추가) |

---

## 4. 비기능 요구사항

### 4.1 성능

| ID | 요구사항 |
|---|---|
| PERF-01 | Docling CPU 추론, 한국어 PDF 10p 기준 **≤ 60초** (로컬 i5-3470 실측 48.8s 확보) |
| PERF-02 | Docling 동시 변환은 `VLM_CONCURRENCY`와 동일한 Semaphore로 제한 |
| PERF-03 | REFINE 동기 응답 ≤ 100 ms (1 MB MD) |
| PERF-04 | REVDOC 1건 end-to-end ≤ 180초 (LLM 호출 포함, 재시도 제외) |

### 4.2 리소스

| ID | 요구사항 |
|---|---|
| RES-01 | VPS 2 vCPU / 8 GB RAM / Swap 4 GB 환경에서 단일 Docling 변환 가능 |
| RES-02 | Docling IBM 모델 캐시 디스크 사용량 ≤ 1 GB |
| RES-03 | torch 포함 Docling 설치 후 Forge 컨테이너 이미지 증가 ≤ 2 GB |

### 4.3 호환성 / 제약

| ID | 요구사항 |
|---|---|
| COMP-01 | v2 SRS의 ROUTE-01~05, EXTRACT-01~05, VLM-01~05, API-01~06, CONFIG-01~04 회귀 금지 |
| COMP-02 | **C1 제약 유지** — Forge 코드베이스에서 `from lightrag import ...` 금지. LightRAG 연계는 callback URL 경유만 |
| COMP-03 | `python -m pytest tests/ -v` 전체 통과 (v2 기준 145+ tests + v3 신규 tests) |
| COMP-04 | Docker 통합 (`docker-compose.integration.yml`)에서 Forge 컨테이너 healthcheck 유지 |

---

## 5. 데이터 모델 확장

### 5.1 신규 테이블

```sql
CREATE TABLE IF NOT EXISTS forge_refine_rules (
    id          SERIAL PRIMARY KEY,
    stage       VARCHAR(30) NOT NULL,  -- encoding, newline, special_char, frontmatter, codefence, traceability
    version     INT NOT NULL,
    config      JSONB NOT NULL,        -- 정규식/매핑 테이블
    is_active   BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX idx_forge_refine_rules_active
    ON forge_refine_rules(stage) WHERE is_active = TRUE;

CREATE TABLE IF NOT EXISTS forge_docling_logs (
    id            SERIAL PRIMARY KEY,
    job_id        UUID REFERENCES forge_jobs(id),
    pages         INT,
    latency_ms    INT,
    fallback      BOOLEAN DEFAULT FALSE,
    fallback_reason TEXT,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);
```

### 5.2 기존 테이블 변경

`forge_jobs.source_format`에 `refine`, `reverse_doc` 추가 허용.
`forge_jobs.route`에 `docling` 추가 허용.
`forge_prompts.type`에 `reverse_doc` 추가 허용.

---

## 6. 롤아웃 Phase

| Phase | 범위 | 완료 조건 |
|---|---|---|
| **Phase 1** | REFINE + CALLBACK | 기존 LightRAG 18 docs를 Forge `/refine` → LightRAG callback 경로로 재업로드 성공 |
| **Phase 2** | REVDOC | PKG_LOAN_BATCH/CALC/LIFECYCLE 3건 역문서 Forge로 생성 (품질 게이트 통과) |
| **Phase 3** | DOCLING + ROUTE 확장 | 한국은행 금융안정보고서 10p 한국어 PDF를 Forge Docling 경로로 처리, 표 구조 보존 확인 |
| **Phase 4** | (별도 SRS) | SME 피드백 루프, 위생 API 통합 |

각 Phase 완료 시 `C:/workspace/lightrag/track_f_forge_extension_phase{N}.md` 매뉴얼 산출.

---

## 7. 참고 / 관련 문서

| 문서 | 위치 |
|---|---|
| Forge v2 SRS | `docs/SRS.md` |
| Forge 하네스 | `CLAUDE.md` (프로젝트 루트) |
| LightRAG PG+AGE 배포 기록 | `C:/workspace/lightrag/track_a_pg_age_migration.md` |
| RAG-Anything 비채용 근거 | `C:/workspace/lightrag/track_e_rag_anything_eval.md` (예정) |
| 전처리 6단계 실증 근거 | memory `project_preprocessing_required` |
| 역문서 프롬프트 원본 | `C:/workspace/day1-plsql-parsing/src/prompts/prompt_A_doc_gen.md` |
| 역문서 템플릿 예시 | `C:/workspace/day1-plsql-parsing/out/generated/PKG_LOAN_BATCH_doc.md` |
| Docling 한국어 실측 자료 | `C:/workspace/docling-test/bok_docling.md` |

---

## 8. 요구사항 ID 인덱스

| 카테고리 | ID 범위 | 개수 |
|---|---|---|
| DOCLING | DOCLING-01~08 | 8 |
| ROUTE (확장) | ROUTE-06~09 | 4 |
| REFINE | REFINE-01~07 | 7 |
| REVDOC | REVDOC-01~08 | 8 |
| CALLBACK | CALLBACK-01~05 | 5 |
| PERF | PERF-01~04 | 4 |
| RES | RES-01~03 | 3 |
| COMP | COMP-01~04 | 4 |
| **합계** | | **43** |
