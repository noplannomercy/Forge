# Forge API 사용 가이드

> 이 문서는 Forge API의 모든 엔드포인트를 실제 요청/응답 예시와 함께 설명한다.
> 기본 URL: `http://localhost:8003` (Docker integration: `http://forge:8003`)

---

## 변환 API

### POST /convert — 문서 변환

파일을 업로드하면 비동기로 변환을 시작하고 job_id를 즉시 반환한다.

**요청:**
```bash
curl -X POST http://localhost:8003/convert \
  -F "file=@안산시_제안서.pdf"
```

**응답 (200):**
```json
{
  "job_id": "a39db89c-e26e-40e3-9f4b-f66e0aa26301",
  "status": "queued"
}
```

**쿼리 파라미터:**

| 파라미터 | 기본값 | 설명 |
|----------|--------|------|
| `route` | 자동 | `extract` 또는 `vlm` 강제 지정 |
| `requested_by` | (없음) | 요청자 식별 (예: `cortex-api`, `n8n-batch`) |
| `callback_url` | (없음) | 완료 시 결과를 POST할 URL |
| `domain` | `general` | 문서 분류 (callback payload에 포함) |

**응용 예시:**

```bash
# VLM 경로 강제 (텍스트 PDF도 VLM으로 처리하고 싶을 때)
curl -X POST "http://localhost:8003/convert?route=vlm" \
  -F "file=@문서.pdf"

# Cortex 연동 (callback + domain 지정)
curl -X POST "http://localhost:8003/convert?callback_url=http://cortex:9000/v1/ingest&domain=legal" \
  -F "file=@계약서.pdf"

# 요청자 추적
curl -X POST "http://localhost:8003/convert?requested_by=n8n-batch-001" \
  -F "file=@보고서.docx"
```

**에러 응답:**

| 상태코드 | 원인 | 예시 |
|----------|------|------|
| 400 | 지원 안 하는 포맷 | `{"detail": "Unsupported format: .csv"}` |
| 413 | 파일 크기 초과 (100MB) | `{"detail": "File too large: max 104857600 bytes"}` |

---

### GET /result/{job_id} — 결과 조회

변환 결과를 조회한다. status가 `completed`가 될 때까지 폴링.

**요청:**
```bash
curl http://localhost:8003/result/a39db89c-e26e-40e3-9f4b-f66e0aa26301
```

**응답 (처리 중):**
```json
{
  "status": "processing",
  "result": null,
  "meta": {},
  "error": null
}
```

**응답 (완료):**
```json
{
  "status": "completed",
  "result": {
    "text": "# 안산시 강소형 스마트도시 제안서\n\n## 1. 사업 개요\n\n...",
    "format": "md",
    "pages": 64,
    "file_name": "안산시_제안서.pdf",
    "source_format": "pdf",
    "route": "vlm",
    "quality": {
      "total_chars": 63835,
      "chars_per_page": 997.4,
      "total_pages": 64,
      "failed_pages": 0,
      "confidence": "high",
      "total_batches": 13,
      "failed_batches": 0,
      "method": "semantic"
    }
  },
  "meta": {
    "category": "스마트도시",
    "title": "안산시 강소형 스마트도시 제안서",
    "summary": "안산시 스마트도시 서비스 구축을 위한 제안",
    "keywords": ["스마트도시", "안산시", "IoT", "빅데이터", "AI"]
  },
  "error": null
}
```

**응답 (실패):**
```json
{
  "status": "failed",
  "result": null,
  "meta": {},
  "error": "LibreOffice conversion failed: ..."
}
```

**마크다운 본문만 받기:**
```bash
curl "http://localhost:8003/result/a39db89c?format=text"
# Content-Type: text/markdown
# 본문만 반환 (JSON 아님)
```

**에러:**

| 상태코드 | 원인 |
|----------|------|
| 404 | 존재하지 않는 job_id |

---

### POST /batch — 배치 변환

여러 파일을 한 번에 변환한다. 각 파일별로 별도 Job이 생성된다.

**요청:**
```bash
curl -X POST http://localhost:8003/batch \
  -F "files=@제안서.docx" \
  -F "files=@보고서.pdf" \
  -F "files=@데이터.xlsx"
```

**응답 (200):**
```json
{
  "jobs": [
    {"file_name": "제안서.docx", "job_id": "abc-001", "status": "queued"},
    {"file_name": "보고서.pdf", "job_id": "abc-002", "status": "queued"},
    {"file_name": "데이터.xlsx", "job_id": "abc-003", "status": "queued"}
  ]
}
```

미지원 포맷이나 크기 초과 파일은 개별 에러로 처리되고, 나머지는 정상 진행:
```json
{
  "jobs": [
    {"file_name": "제안서.docx", "job_id": "abc-001", "status": "queued"},
    {"file_name": "데이터.csv", "error": "Unsupported format: .csv"},
    {"file_name": "거대파일.pdf", "error": "File too large: max 104857600 bytes"}
  ]
}
```

batch도 convert와 동일한 쿼리 파라미터를 지원한다:
```bash
curl -X POST "http://localhost:8003/batch?callback_url=http://cortex:9000/v1/ingest&domain=finance" \
  -F "files=@a.docx" -F "files=@b.pdf"
```

---

### GET /health — 헬스체크

서비스 생존 확인. Docker healthcheck, ALB, 모니터링에서 사용.

```bash
curl http://localhost:8003/health
# {"status": "ok"}
```

---

## 관리 API

모든 관리 API는 `X-Forge-Key` 헤더 인증이 필요하다.
`.env`에 `FORGE_API_KEY`를 설정해야 활성화된다. 빈 값이면 관리 API 전체 비활성화.

```bash
# 모든 관리 API 요청에 이 헤더 포함
-H "X-Forge-Key: 여기에_FORGE_API_KEY_값"
```

---

### GET /jobs — Job 목록

변환 작업 목록 조회. 필터링 + 페이지네이션 지원.

```bash
# 전체 조회
curl -H "X-Forge-Key: key" http://localhost:8003/jobs

# 상태 필터
curl -H "X-Forge-Key: key" "http://localhost:8003/jobs?status=completed"

# 포맷 필터
curl -H "X-Forge-Key: key" "http://localhost:8003/jobs?source_format=pdf"

# 복합 필터 + 페이지네이션
curl -H "X-Forge-Key: key" "http://localhost:8003/jobs?status=completed&source_format=docx&page=2&page_size=10"
```

**응답:**
```json
[
  {
    "id": "a39db89c-...",
    "file_name": "제안서.pdf",
    "status": "completed",
    "source_format": "pdf",
    "route": "vlm",
    "method": "semantic",
    "created_at": "2026-04-09T10:30:00Z",
    "processing_ms": 45200
  }
]
```

목록에는 result_text(본문)가 포함되지 않는다. 성능을 위해 요약 정보만.

---

### GET /jobs/{id} — Job 상세

단건 상세 조회. result_text 포함.

```bash
curl -H "X-Forge-Key: key" http://localhost:8003/jobs/a39db89c-...
```

---

### PATCH /jobs/{id}/meta — 메타 수정

자동 추출된 메타데이터를 수동으로 수정하거나 보강한다. 기존 메타에 merge.

```bash
curl -X PATCH -H "X-Forge-Key: key" -H "Content-Type: application/json" \
  -d '{"category": "수정된_카테고리", "department": "전략기획팀"}' \
  http://localhost:8003/jobs/a39db89c.../meta
```

기존 meta: `{"category": "스마트도시", "title": "..."}` 에
`{"category": "수정된_카테고리", "department": "전략기획팀"}` 을 merge하면:
```json
{
  "category": "수정된_카테고리",
  "title": "...",
  "department": "전략기획팀"
}
```

---

### POST /jobs/{id}/retry — 메타 재추출

파일을 다시 변환하지 않고, 기존 변환 결과에서 메타만 다시 추출한다.
프롬프트 업데이트 후 기존 결과에 새 프롬프트를 적용하고 싶을 때 사용.

```bash
curl -X POST -H "X-Forge-Key: key" http://localhost:8003/jobs/a39db89c.../retry
```

---

### DELETE /jobs/{id} — 삭제 (soft delete)

완전 삭제가 아니라 `deleted_at`을 기록. 목록에서 제외되지만 DB에는 남아있음.

```bash
curl -X DELETE -H "X-Forge-Key: key" http://localhost:8003/jobs/a39db89c...
```

---

### GET /stats/daily — 일별 통계

```bash
curl -H "X-Forge-Key: key" "http://localhost:8003/stats/daily?from=2026-04-07&to=2026-04-11"
```

**응답:**
```json
[
  {
    "date": "2026-04-09",
    "total": 15,
    "success": 14,
    "failed": 1,
    "avg_processing_ms": 12500
  }
]
```

---

### GET /stats/cost — 비용 집계

VLM 호출 비용을 일별로 집계한다. forge_vlm_logs 테이블 기반.

```bash
curl -H "X-Forge-Key: key" "http://localhost:8003/stats/cost?from=2026-04-07&to=2026-04-11"
```

---

### GET /stats/models — 모델별 통계

어떤 VLM 모델이 얼마나 호출됐는지, 평균 지연시간, 총 토큰 수.

```bash
curl -H "X-Forge-Key: key" http://localhost:8003/stats/models
```

**응답:**
```json
[
  {
    "model": "google/gemini-2.0-flash-001",
    "calls": 50,
    "avg_latency_ms": 3200,
    "total_input_tokens": 125000,
    "total_output_tokens": 45000,
    "total_cost_usd": 1.25
  }
]
```

---

### GET /prompts — 프롬프트 버전 목록

DB에 저장된 모든 프롬프트 버전 이력.

```bash
curl -H "X-Forge-Key: key" http://localhost:8003/prompts
```

---

### GET /prompts/{type}/active — 활성 프롬프트

현재 사용 중인 프롬프트 조회. type: `semantic` 또는 `meta_extract`.

```bash
curl -H "X-Forge-Key: key" http://localhost:8003/prompts/semantic/active
```

**응답:**
```json
{
  "id": 3,
  "type": "semantic",
  "version": 2,
  "text": "이 문서 페이지들을 분석해서 의미 중심으로 재구성해...",
  "is_active": true,
  "created_at": "2026-04-09T11:00:00Z"
}
```

---

### POST /prompts — 새 프롬프트 등록

새 버전을 등록하면 기존 버전은 자동 비활성화. 코드 배포 없이 프롬프트 교체.

```bash
curl -X POST -H "X-Forge-Key: key" -H "Content-Type: application/json" \
  -d '{"type": "semantic", "text": "새로운 프롬프트 내용..."}' \
  http://localhost:8003/prompts
```

**응답:**
```json
{
  "id": 4,
  "type": "semantic",
  "version": 3,
  "text": "새로운 프롬프트 내용...",
  "is_active": true,
  "created_at": "2026-04-11T14:00:00Z"
}
```

---

## 지원 포맷

| 포맷 | 확장자 | Content-Type |
|------|--------|-------------|
| PDF | .pdf | application/pdf |
| DOCX | .docx | application/vnd.openxmlformats-officedocument.wordprocessingml.document |
| PPTX | .pptx | application/vnd.openxmlformats-officedocument.presentationml.presentation |
| XLSX | .xlsx | application/vnd.openxmlformats-officedocument.spreadsheetml.sheet |
| HWPX | .hwpx | application/hwp+zip |
| JPEG | .jpg, .jpeg | image/jpeg |
| PNG | .png | image/png |
| TIFF | .tiff, .tif | image/tiff |
| BMP | .bmp | image/bmp |

**미지원:** HWP(구형 바이너리), CSV, TXT, HTML, XML 등 → HTTP 400

---

## Swagger UI

브라우저에서 직접 API를 테스트할 수 있다.

```
http://localhost:8003/docs
```

FastAPI가 자동 생성하는 OpenAPI 문서. 모든 엔드포인트의 파라미터, 응답 스키마 포함.

---

## 폴링 패턴 예시

```python
import time
import requests

# 1. 파일 업로드
resp = requests.post("http://localhost:8003/convert",
                     files={"file": open("문서.pdf", "rb")})
job_id = resp.json()["job_id"]

# 2. 결과 폴링
while True:
    result = requests.get(f"http://localhost:8003/result/{job_id}").json()
    if result["status"] == "completed":
        print(result["result"]["text"])
        break
    elif result["status"] == "failed":
        print("실패:", result["error"])
        break
    time.sleep(2)  # 2초 간격 폴링
```

callback_url을 쓰면 폴링 없이 자동 전달받을 수 있다. Cortex 연동 시 권장.
