# SRS: Forge — Document Converter Service v2

다양한 포맷(스캔 PDF, DOCX, PPTX, XLSX, 이미지)을 깨끗한 Markdown으로 변환하는 독립 마이크로서비스.
포맷별 최적 경로(추출 vs VLM)로 처리하며, VLM은 이미지 기반 문서에만 사용.

---

## 기능 요구사항

### ROUTE — 포맷 감지 및 경로 결정

| ID | 요구사항 |
|----|----------|
| ROUTE-01 | 업로드된 파일의 확장자로 포맷을 감지한다 |
| ROUTE-02 | DOCX, PPTX, XLSX는 추출(extract) 경로로 라우팅한다 |
| ROUTE-03 | JPG, JPEG, PNG, TIFF, BMP는 VLM 경로로 라우팅한다 |
| ROUTE-04 | PDF는 텍스트 추출을 시도하고, chars_per_mb < 100이면 VLM, 아니면 추출 경로로 라우팅한다 |
| ROUTE-05 | 지원하지 않는 확장자는 UnsupportedFormat 에러를 반환한다 |

### EXTRACT — 텍스트 기반 추출

| ID | 요구사항 |
|----|----------|
| EXTRACT-01 | DOCX에서 텍스트와 표를 추출하여 Markdown으로 변환한다 (python-docx) |
| EXTRACT-02 | PPTX에서 슬라이드별 텍스트를 추출하여 Markdown으로 변환한다 (python-pptx) |
| EXTRACT-04 | XLSX에서 시트별 데이터를 추출하여 Markdown 표로 변환한다 (openpyxl) |
| EXTRACT-05 | 텍스트 PDF에서 텍스트를 추출하여 Markdown으로 변환한다 |

### VLM — 이미지 기반 변환

| ID | 요구사항 |
|----|----------|
| VLM-01 | PDF 페이지를 pypdfium2로 이미지로 변환한다 |
| VLM-02 | 이미지를 OpenAI-compatible VLM 엔드포인트에 전송하여 Markdown을 받는다 |
| VLM-03 | VLM 프롬프트는 텍스트 추출, 표 변환, 이미지 설명, 헤딩 변환 규칙을 포함한다 |
| VLM-04 | 이미지 파일(JPG/PNG 등)은 직접 VLM에 전달한다 |
| VLM-05 | VLM 타임아웃은 환경변수(VLM_TIMEOUT)로 설정 가능하다 (기본 120초) |

### API — REST 엔드포인트

| ID | 요구사항 |
|----|----------|
| API-01 | `POST /convert` — multipart/form-data로 파일을 받아 job_id를 즉시 반환한다 |
| API-02 | `GET /result/{job_id}` — 변환 결과를 조회한다 (status: queued/processing/completed/failed) |
| API-03 | 변환 완료 시 응답에 text, format, pages, file_name, source_format, route, quality를 포함한다 |
| API-04 | `POST /batch` — 여러 파일을 받아 job_id 리스트를 반환한다 |
| API-05 | `GET /health` — 서비스 상태를 반환한다 (`{"status": "ok"}`) |
| API-06 | quality 필드에 total_chars, chars_per_page, confidence를 포함한다 |

### CONFIG — 환경 설정

| ID | 요구사항 |
|----|----------|
| CONFIG-01 | VLM_URL 환경변수로 VLM 엔드포인트를 설정한다 (기본: http://localhost:11434/v1/chat/completions) |
| CONFIG-02 | VLM_MODEL 환경변수로 모델을 설정한다 (기본: qwen2-vl:7b) |
| CONFIG-03 | VLM_API_KEY 환경변수로 API 키를 설정한다 (선택) |
| CONFIG-04 | VLM_TIMEOUT 환경변수로 타임아웃을 설정한다 (기본: 120) |

---

## 데이터 모델 개요

```
Jobs (비동기 작업 관리)
  - id: uuid PK
  - status: enum (queued, processing, completed, failed)
  - file_name: text
  - source_format: text (pdf, docx, pptx, hwpx, xlsx, jpg, png, ...)
  - route: text (vlm, extract)
  - result: jsonb nullable (변환 완료 시)
  - error: text nullable (실패 시)
  - created_at: timestamp
  - completed_at: timestamp nullable
```

> 영속 DB 없이 인메모리 dict로 시작. 필요 시 SQLite/Redis 전환.

---

## 상태 정의

**Job 상태 전이:**

```
queued → processing → completed
                    → failed
```

- `queued`: 요청 접수, 큐 대기
- `processing`: Worker가 변환 중
- `completed`: 변환 완료, result 필드에 결과
- `failed`: 변환 실패, error 필드에 원인

---

## 엔드포인트 목록

| Method | URL | 설명 |
|--------|-----|------|
| POST | `/convert` | 파일 업로드 → job_id 반환 |
| GET | `/result/{job_id}` | 변환 결과 조회 |
| POST | `/batch` | 다중 파일 업로드 → job_id 리스트 반환 |
| GET | `/health` | 헬스체크 |

---

## 개발 범위 외 (Out of Scope)

- 페이지 병렬 VLM 호출
- 변환 결과 캐싱 (같은 파일 재변환 방지)
- VLM 비용 추적
- 혼합 모드 (일부 페이지만 VLM)
- 추출 경로 결과에 VLM 보정 (표 정리 등)
- HWPX 지원 (추후 API 기반 추가)
- 인증/인가
- Cortex 코드 수정
