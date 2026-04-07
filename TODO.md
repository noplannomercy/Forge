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
- LibreOffice, Docling, GPU 불필요

## v2 — 멀티모달 확장 (수동 테스트에서 도출, 우선순위 높음)

- [ ] **PPTX/DOCX VLM 경로 추가** — 슬라이드/페이지별 이미지 렌더링 → VLM
  - PPTX는 이미지/도표/그림 위주라 extract만으로 답 없음 (수동 테스트 확인)
  - DOCX는 텍스트 위주라 extract로 쓸만하지만, 이미지 많은 문서는 동일 문제
  - 라우터에서 `?mode=text`/`?mode=visual` 파라미터로 사용자 선택 또는 자동 분기
- [ ] **quality 메타에 이미지 정보 추가** — 임베디드 이미지 개수/비율 포함
  - 현재 confidence:"high"만으로는 이미지 누락 여부를 Cortex(LLM)가 판단 불가
  - Cortex에서 "이 변환 결과가 신뢰할 만한가" 판단할 근거 필요
- [ ] **결과 다운로드 엔드포인트** — `/result/{job_id}?format=text` 또는 `/result/{job_id}/download`
  - 현재 JSON 감싸서 반환 → 마크다운 텍스트만 바로 받을 수 있어야 Cortex 연동 편함

## 향후 개선 (v3)

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
| PPTX | 2건 | **불충분** | 이미지/도표 위주, VLM 없이 답 없음 |
| XLSX | (unit test) | **양호** | 표 추출 정확 |
| PDF (스캔) | 1건 (25.6MB, 64p) | VLM 경로 정상 분기 | VLM 서버 없어 64페이지 전부 실패 placeholder |

## 범위 외 (영구)

- 변환 결과 캐싱
- VLM 비용 추적
- 추출 경로 결과에 VLM 보정
