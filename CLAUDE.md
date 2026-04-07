# 작업 시작 전

- 이 파일을 끝까지 읽은 뒤 작업을 시작할 것
- `python -m pytest tests/ -v`로 현재 테스트 상태 확인 후 작업 시작
- `.env`에 `VLM_URL`과 `VLM_MODEL`이 설정되어 있는지 확인

---

# 개요

Forge는 다양한 포맷(PDF, DOCX, PPTX, XLSX, 이미지)을 Markdown으로 변환하는 독립 마이크로서비스다. 텍스트 문서는 추출(extract), 이미지 기반 문서(PPTX, 스캔 PDF)는 VLM semantic 배치로 의미 재구성 처리. 비동기 Job 기반. Cortex(:8000)와 완전 독립, 포트 8003.

---

# 제약 사항

| # | 규칙 | 이유 |
|---|------|------|
| C1 | Cortex 코드 수정 금지 | 완전 독립 서비스 원칙. Cortex 의존성 0. |
| C2 | DOCX/XLSX는 extract, PPTX/이미지PDF/이미지는 VLM semantic | PPTX는 이미지 위주라 extract 무의미(수동 테스트 확인). DOCX/XLSX는 extract가 쓸만함. |
| C3 | JobStore 인터페이스를 우회하여 Job dict에 직접 접근 금지 | Redis 전환 시 코드 변경 최소화를 위한 추상화. |
| C4 | asyncio.create_task 호출 시 반드시 _safe_process 래퍼 사용 | fire-and-forget에서 예외가 삼켜지는 문제. 래퍼 없이 create_task 직접 호출 금지. |
| C5 | API 키, 시크릿 하드코딩 금지 | .env 또는 환경변수 사용. config.py의 pydantic-settings로 관리. |

---

# 준수 사항

| # | 규칙 |
|---|------|
| S1 | VLM 호출은 반드시 Semaphore(VLM_CONCURRENCY) 안에서 실행 |
| S2 | VLM 호출 실패 시 3회 retry (지수 백오프 1s, 2s, 4s) 후 BatchResult.error로 기록 |
| S3 | 멀티 배치 VLM 처리 시 부분 실패 허용 — 실패 배치는 placeholder, 성공 배치는 보존 |
| S4 | 모든 extractor는 `async def extract(file_bytes: bytes, file_name: str) -> ConvertResult` 시그니처 준수 |
| S5 | 파일 업로드 시 MAX_FILE_SIZE(100MB) 초과 체크 후 413 반환 |

---

# 스택

| 기술 | 용도 |
|------|------|
| Python 3.11+ | 런타임 |
| FastAPI + uvicorn | REST API (포트 8003) |
| httpx (async) | VLM API 호출 (OpenAI-compatible) |
| pydantic-settings | 환경변수 관리 |
| pypdfium2 | PDF → 이미지 변환 + 텍스트 추출 |
| Pillow | 이미지 전처리 |
| python-docx | DOCX → md |
| python-pptx | PPTX → md (extract용, v2에서 VLM 경로 추가) |
| openpyxl | XLSX → md |
| LibreOffice headless | PPTX → PDF 변환 (soffice --headless) |

---

# 구조

| 경로 | 역할 |
|------|------|
| `app.py` | FastAPI 엔드포인트 (/convert, /result/{job_id}, /batch, /health) + ?route= + ?requested_by= + ?format=text |
| `router.py` | 포맷 감지 + 경로 결정 (extract vs vlm) + route_override 지원 |
| `vlm.py` | VLM semantic 배치 클라이언트 (process_batch + Semaphore + retry + 토큰/비용 추적) |
| `job_store.py` | JobStore ABC + InMemoryJobStore + PostgresJobStore + VLMLogStore |
| `worker.py` | 비동기 변환 워커 (extract/vlm 라우팅 + PPTX→PDF + 메타 추출) |
| `config.py` | 환경변수 로드 (VLM, VLM_BATCH_SIZE, DATABASE_URL, META_LLM_* 등) |
| `models.py` | Pydantic 모델 (Job, ConvertResult, DocumentResult, Quality, BatchResult) |
| `meta.py` | LLM 메타 자동 추출 클라이언트 (VLM fallback) |
| `schema.sql` | PostgreSQL DDL (forge_jobs, forge_vlm_logs, 인덱스) |
| `extractors/docx.py` | DOCX 텍스트+표 → md |
| `extractors/pptx.py` | PPTX 슬라이드별 → md (extract 경로용, VLM 경로는 office.py 경유) |
| `extractors/xlsx.py` | XLSX 시트별 → md 표 |
| `extractors/pdf.py` | PDF 텍스트 추출 + 이미지 변환 |
| `extractors/image.py` | 이미지 → VLM 전달용 PNG 변환 |
| `extractors/office.py` | LibreOffice headless PPTX→PDF 변환 |

---

# 하네스 진화 원칙

- 이 파일은 코드와 함께 진화한다. 새 제약/실패를 발견하면 즉시 반영한다.
- 제약 사항에는 반드시 "왜 금지하는지" 이유를 적는다 (과거 사고 기반).
- 변하는 것(진행 상태, TODO, 구현 순서)은 이 파일에 넣지 않는다. → TODO.md 참조.
- 구조 테이블이 실제 파일과 다르면 즉시 갱신한다.

---

# 완료 조건

```bash
# 테스트 전체 통과
python -m pytest tests/ -v
# 예상: 104+ passed (v3 기준, .env로 인한 test_config_defaults 1개 실패는 허용)

# 서버 기동 확인
uvicorn app:app --port 8003
curl http://localhost:8003/health
# 예상: {"status":"ok"}

# 린트 (설치 시)
ruff check .
```

---

# 참조 문서

| 문서 | 설명 |
|------|------|
| docs/SRS.md | 요구사항 (21개 ID) |
| docs/superpowers/specs/2026-04-07-forge-converter-design.md | v1 설계 스펙 |
| docs/superpowers/specs/2026-04-07-forge-semantic-vlm-design.md | v2 semantic VLM 스펙 |
| docs/superpowers/specs/2026-04-07-forge-db-meta-design.md | v3 DB + 메타 추출 스펙 |
| docs/superpowers/plans/2026-04-07-forge-converter.md | v1 구현 플랜 (12 Task) |
| docs/superpowers/plans/2026-04-07-forge-semantic-vlm.md | v2 구현 플랜 (7 Task) |
| docs/superpowers/plans/2026-04-07-forge-db-meta.md | v3 구현 플랜 (7 Task) |
| docs/2026-04-07-document-converter-service-v2.md | office-hours 원본 설계 |
| TODO.md | 전체 로드맵 + 진행 상태 (specs/plans의 상위 문서) |
