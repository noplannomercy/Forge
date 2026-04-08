# Forge — Document Converter Service v2 TODO

> office-hours 결과 기반 (2026-04-07)

## 구현 필수 (v1 완료 — 2026-04-07)

- [x] FastAPI 앱 뼈대 (app.py — /convert, /health)
- [x] 포맷 감지 + 경로 결정 로직 (router.py)
- [x] VLM 클라이언트 — OpenAI-compatible 엔드포인트 호출 (vlm.py)
- [x] PDF extractor — pypdfium2 이미지 변환 + 텍스트 추출 판별 (extractors/pdf.py)
- [x] DOCX extractor — python-docx 텍스트+표 → md (extractors/docx.py)
- [x] PPTX extractor — python-pptx 슬라이드별 → md (extractors/pptx.py)
- [x] XLSX extractor — openpyxl 시트별 → md (extractors/xlsx.py)
- [x] 이미지 handler — 이미지 → VLM 전달 (extractors/image.py)
- [x] 환경변수 설정 (config.py — VLM_URL, VLM_MODEL, VLM_TIMEOUT)
- [x] Async Job 처리 모델 — POST /convert → job_id 반환, GET /result/{job_id}
- [x] Batch API — POST /batch
- [x] _safe_process 래퍼 (create_task 예외 로깅)
- [x] VLM 3회 retry (지수 백오프 1s, 2s, 4s)
- [x] MAX_FILE_SIZE 100MB 체크 → 413

## 인프라 (v1 완료)

- [x] Dockerfile
- [x] requirements.txt
- [x] .env.example

## 설계 결정 사항 (확정)

- Cortex와 완전 독립 — Cortex 코드 수정 0
- VLM은 이미지 기반 문서에만 사용 (텍스트 있으면 추출)
- OpenAI-compatible 엔드포인트 하나로 VLM provider 통일

## v2 — Semantic VLM (스펙+플랜 완료, 구현 대기)

> 스펙: docs/superpowers/specs/2026-04-07-forge-semantic-vlm-design.md
> 플랜: docs/superpowers/plans/2026-04-07-forge-semantic-vlm.md

- [x] Task 1: Config + Models 확장 (vlm_batch_size, Quality 배치 필드)
- [x] Task 2: VLM Client semantic 배치 모드 (process_batch, 멀티 이미지)
- [x] Task 3: LibreOffice headless 래퍼 (PPTX→PDF)
- [x] Task 4: Router — PPTX→VLM + `?route=` 파라미터
- [x] Task 5: Worker — PPTX 파이프라인 + semantic 결과 조립
- [x] Task 6: API — route 쿼리 파라미터
- [x] Task 7: Dockerfile + 최종 검증

핵심 변경:
- VLM 경로를 페이지별 OCR → **배치 단위 semantic 재구성**으로 교체
- PPTX → LibreOffice headless → PDF → 이미지 → semantic VLM
- `?route=extract|vlm` 파라미터로 강제 지정 가능
- quality 메타에 total_batches/failed_batches/method 추가

## v2 — 추가 개선 (semantic 이후)

- [ ] **semantic 프롬프트 품질 개선** — 수동 테스트에서 도출
  - 다이어그램 설명이 너무 단순 — 화살표 관계, 계층 구조, 인과관계 명시 필요
  - 이미지 안 세부 텍스트 의미 파악 부족 — 모델 업그레이드(Gemini 2.5 Flash, GPT-4o) 또는 프롬프트 튜닝으로 개선
  - 배치 간 내용 중복 발생 — 프롬프트에 "이전 배치 내용 반복 금지" 지시 추가 검토
- [ ] **결과 다운로드 엔드포인트** — `/result/{job_id}?format=text` 또는 `/result/{job_id}/download`
  - 현재 JSON 감싸서 반환 → 마크다운 텍스트만 바로 받을 수 있어야 Cortex 연동 편함

## v3 — DB + LLM 메타 추출 (구현 완료 — 2026-04-08)

> 스펙: docs/superpowers/specs/2026-04-07-forge-db-meta-design.md
> 플랜: docs/superpowers/plans/2026-04-07-forge-db-meta.md

- [x] Task 1: 스키마 + Config + 의존성 (schema.sql, DATABASE_URL, META_LLM_*, asyncpg)
- [x] Task 2: Models 확장 (Job에 meta, requested_by, prompt_version 등)
- [x] Task 3: PostgresJobStore + VLMLogStore (asyncpg)
- [x] Task 4: MetaExtractor — LLM 메타 자동 추출 (VLM fallback)
- [x] Task 5: BatchResult 토큰/비용 정보 추가
- [x] Task 6: Worker — 메타 추출 단계 + VLM 로그 기록
- [x] Task 7: API — requested_by, ?format=text, DB pool lifecycle

핵심:
- Cortex PostgreSQL에 forge_ 테이블 (forge_jobs, forge_vlm_logs, forge_daily_stats view)
- 파일 넣으면 변환 후 LLM이 자동으로 메타 추출 → JSONB 저장
- MetaExtractor는 app.state singleton (eng-review 반영)
- DB pool startup/shutdown lifecycle (eng-review 반영)

eng-review 발견사항 (플랜에 반영 완료):
- save_result COALESCE(started_at, created_at)
- InMemoryJobStore.save_meta() 추가
- meta.py JSON 파싱 강화 (첫{~마지막} 추출)
- extract 경로 메타 추출 테스트 추가

## v3 — 관리 API + LLMOps (v3 DB 완료 후)

- [ ] **관리 API** — Cortex 백오피스가 호출할 엔드포인트
  - `GET /jobs` — Job 목록 조회 (status, source_format, requested_by 필터 + 페이징)
  - `GET /jobs/{id}/meta` — 메타 조회/수정
  - `GET /stats/daily` — 일별 변환 건수/성공률/비용 (forge_daily_stats)
  - `GET /stats/cost` — 모델별/기간별 VLM 비용 집계 (forge_vlm_logs)
  - `POST /jobs/{id}/retry` — 재처리
  - `DELETE /jobs/{id}` — 삭제
- [ ] **LLMOps API** — 프롬프트 버전 관리, A/B 테스트, 코드 배포 없이 프롬프트 교체
- [ ] **품질 관리 API** — 변환 결과 평가/피드백 루프
- 백오피스 UI/대시보드는 Cortex 쪽 — Forge는 API만 제공

v3 코드 리뷰 수정 완료 (2026-04-08):
- [x] save_meta를 JobStore ABC에 추가 (default no-op)
- [x] PostgresJobStore._row_to_job에서 ConvertResult 재구성
- [x] on_event deprecated → lifespan context manager 마이그레이션
- [x] worker hasattr 제거 → ABC 계약 사용

v3 코드 리뷰 defer 항목:
- [ ] MetaExtractor retry 추가 (현재 0회, 최소 1회 추천)
- [ ] processing_ms SQL CAST(... AS INT) 명시
- [ ] asyncpg TYPE_CHECKING import (IDE 지원)
- [ ] **VLMLogStore worker 연결** — 생성만 되고 실제 로그 안 쌓임 (대시보드용 데이터 없음)
- [ ] MetaExtractor에 temperature:0 설정 (JSON 추출 일관성)
- [ ] PostgreSQL 통합 테스트 (CI/CD에서 처리)
- [ ] VLMClient singleton화 (현재 Job당 생성, 빈도 낮아서 당장 안 급함)
- [ ] materialized view REFRESH 전략 (cron 또는 API 호출 시)

## 향후 개선 (인프라)

- [ ] Redis 기반 JobStore + Worker 분리 + 파일 스트리밍(SpooledTemporaryFile)
  - 현재 인메모리 dict + file_bytes 전체 메모리 적재 방식
  - 동시 요청 증가 시 메모리 압박 → Redis 전환과 파일 스트리밍을 묶어서 처리
  - JobStore 인터페이스 이미 분리되어 있으므로 RedisJobStore 교체만 필요
- [ ] HWPX 지원 (API 기반 추가)
- [ ] hybrid route (페이지 단위 extract→VLM fallback)
- [ ] quality gate (weighted scoring: chars_per_page + table_integrity + heading_preservation)
- [ ] sync mode (?sync=true)
- [ ] callback_url (완료 시 POST 알림)
- [ ] Job TTL + 자동 정리
- [ ] DELETE /jobs/{job_id} (취소)
- [ ] POST /retry/{job_id}
- [ ] GET /formats

## 수동 테스트 결과 (2026-04-07)

| 포맷 | 테스트 | extract 품질 | 비고 |
|------|--------|-------------|------|
| DOCX | 3건 | **쓸만함** | 텍스트+표 위주, 이미지 없는 문서들 |
| PPTX (v1 extract) | 2건 | **불충분** | 이미지/도표 위주, extract만으로 답 없음 |
| PPTX (v2 semantic) | 1건 | **쓸만함** | LibreOffice→PDF→VLM, 다이어그램 추출 성공 |
| PDF (v2 semantic) | 1건 (25.6MB, 64p) | **쓸만함** | 48,868자 구조화 마크다운, 13배치 전부 성공 |
| XLSX | (unit test) | **양호** | 표 추출 정확 |
| PDF (스캔) | 1건 (25.6MB, 64p) | VLM 경로 정상 분기 | VLM 서버 없어 64페이지 전부 실패 placeholder |

## 범위 외 (영구)

- 변환 결과 캐싱
- VLM 비용 추적
- 추출 경로 결과에 VLM 보정
