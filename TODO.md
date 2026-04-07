# Forge — Document Converter Service v2 TODO

> office-hours 결과 기반 (2026-04-07)

## 구현 필수

- [ ] FastAPI 앱 뼈대 (app.py — /convert, /health)
- [ ] 포맷 감지 + 경로 결정 로직 (router.py)
- [ ] VLM 클라이언트 — OpenAI-compatible 엔드포인트 호출 (vlm.py)
- [ ] PDF extractor — pypdfium2 이미지 변환 + 텍스트 추출 판별 (extractors/pdf.py)
- [ ] DOCX extractor — python-docx 텍스트+표 → md (extractors/docx.py)
- [ ] PPTX extractor — python-pptx 슬라이드별 → md (extractors/pptx.py)
- [ ] XLSX extractor — openpyxl 시트별 → md (extractors/xlsx.py)
- [ ] 이미지 handler — 이미지 → VLM 전달 (extractors/image.py)
- [ ] 환경변수 설정 (config.py — VLM_URL, VLM_MODEL, VLM_TIMEOUT)
- [ ] Async Job 처리 모델 — POST /convert → job_id 반환, GET /result/{job_id}
- [ ] Batch API — POST /batch (선택)

## 인프라

- [ ] Dockerfile
- [ ] requirements.txt
- [ ] .env.example

## 설계 결정 사항 (확정)

- Cortex와 완전 독립 — Cortex 코드 수정 0
- VLM은 이미지 기반 문서에만 사용 (텍스트 있으면 추출)
- OpenAI-compatible 엔드포인트 하나로 VLM provider 통일
- LibreOffice, Docling, GPU 불필요

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

## 범위 외 (영구)

- 변환 결과 캐싱
- VLM 비용 추적
- 추출 경로 결과에 VLM 보정
