# Forge 관리 API — Design Spec

> 2026-04-08 | Forge v3 관리 API

## 배경

v3에서 PostgreSQL + 메타 추출이 완성되어 DB에 데이터가 쌓이지만, 조회/관리할 API가 `/result/{job_id}` 하나뿐이다. 운영자(LLMOps팀)와 Cortex 백오피스가 Job 목록 조회, 통계, 메타 수정, 재처리 등을 할 수 있어야 한다.

## 목표

Cortex 백오피스 + 운영자(curl/Postman)가 사용하는 관리 API 8개 엔드포인트 구현.

## 설계 결정사항

| 결정 | 선택 | 이유 |
|------|------|------|
| 호출자 | Cortex + 운영자 직접 (curl/Postman) | 내부 운영 도구 |
| 인증 | API 키 (`X-Forge-Key` 헤더) | 최소한의 접근 제어 |
| 인증 범위 | 관리 API만 (`/jobs/*`, `/stats/*`) | 기존 /convert, /result, /batch, /health는 인증 없이 유지 |
| 인증 미설정 시 | 비활성화 (FORGE_API_KEY 빈 값) | 개발 편의 |
| 삭제 방식 | soft delete (`deleted_at` 타임스탬프) | 운영 데이터는 SLA/자산평가용, 함부로 삭제 안 됨 |
| retry 범위 | 메타만 재추출 (result_text 기반) | 원본 파일 없으므로 전체 재변환 불가 |
| 라우터 분리 | `admin.py` (APIRouter) | app.py 비대화 방지 |

## 인증

```
관리 API 요청 시 X-Forge-Key 헤더 필수
키 값: 환경변수 FORGE_API_KEY
미설정 (빈 값) → 인증 비활성화 (개발 모드)
키 불일치 → 401 Unauthorized

기존 엔드포인트 (/convert, /result, /batch, /health) → 인증 없음
```

## 엔드포인트

### 조회

#### `GET /jobs`

Job 목록 조회 (필터 + 페이징).

```
Query params:
  status: str (optional) — queued | processing | completed | failed
  source_format: str (optional) — pdf | docx | pptx | xlsx | jpg | png ...
  requested_by: str (optional)
  page: int (default 1)
  size: int (default 20, max 100)

Response:
{
  "jobs": [
    {
      "id": "uuid",
      "file_name": "안산시_제안서.pdf",
      "status": "completed",
      "route": "vlm",
      "method": "semantic",
      "source_format": "pdf",
      "requested_by": "cortex-api",
      "meta": {"category": "스마트도시", "client": "안산시", ...},
      "processing_ms": 84000,
      "created_at": "2026-04-08T10:00:00Z"
    },
    ...
  ],
  "total": 150,
  "page": 1,
  "size": 20
}

참고: result_text는 목록에서 제외 (본문 무거움)
```

#### `GET /jobs/{id}`

단건 상세 조회. DB 전체 필드 반환.

```
Response:
{
  "id": "uuid",
  "file_name": "...",
  "file_size": 25600000,
  "status": "completed",
  "route": "vlm",
  "method": "semantic",
  "source_format": "pdf",
  "requested_by": "cortex-api",
  "result_text": "## 안산시 강소형 스마트도시...",
  "meta": {...},
  "quality": {...},
  "prompt_version": "semantic-v1",
  "meta_prompt_version": "meta-v1",
  "processing_ms": 84000,
  "created_at": "...",
  "started_at": "...",
  "completed_at": "...",
  "error": null
}

404: Job not found
404: Job deleted (deleted_at이 있으면)
```

#### `GET /stats/daily`

일별 변환 통계.

```
Query params:
  from: date (optional, default 7일 전)
  to: date (optional, default 오늘)

Response:
{
  "stats": [
    {"day": "2026-04-07", "total": 10, "success": 8, "failed": 2, "avg_ms": 5000},
    {"day": "2026-04-08", "total": 5, "success": 5, "failed": 0, "avg_ms": 3000}
  ]
}
```

#### `GET /stats/cost`

비용 집계.

```
Query params:
  from: date (optional, default 7일 전)
  to: date (optional, default 오늘)

Response:
{
  "stats": [
    {"day": "2026-04-07", "total_cost_usd": 0.05, "total_tokens": 15000},
    {"day": "2026-04-08", "total_cost_usd": 0.02, "total_tokens": 8000}
  ]
}
```

#### `GET /stats/models`

모델별 사용량/성능.

```
Response:
{
  "models": [
    {
      "model": "google/gemini-2.0-flash-001",
      "calls": 50,
      "avg_latency_ms": 3000,
      "total_cost_usd": 0.03,
      "total_input_tokens": 10000,
      "total_output_tokens": 5000
    }
  ]
}
```

### 수정

#### `PATCH /jobs/{id}/meta`

메타 수정 (merge). LLM 자동 추출 결과가 틀렸을 때 운영자가 직접 수정.

```
Request body:
{"category": "수정됨", "client": "변경된 고객명"}

동작: 기존 meta에 merge (전체 덮어쓰기 아님)
  기존: {"category": "제안서", "title": "...", "client": "안산시"}
  PATCH: {"category": "수정됨", "client": "변경"}
  결과: {"category": "수정됨", "title": "...", "client": "변경"}

Response: 200 + 업데이트된 meta 전체
404: Job not found
```

#### `POST /jobs/{id}/retry`

메타 재추출. result_text를 기반으로 MetaExtractor 재호출.

```
동작:
  1. Job 조회 → result_text 확인
  2. MetaExtractor.extract(result_text) 호출
  3. meta 업데이트 + meta_prompt_version 갱신

Response: 200 + 재추출된 meta
404: Job not found
400: result_text가 없는 Job (아직 완료 안 됨)
```

#### `DELETE /jobs/{id}`

Soft delete. `deleted_at` 타임스탬프 기록.

```
동작: UPDATE forge_jobs SET deleted_at = NOW() WHERE id = $1
/jobs 목록에서 제외 (deleted_at IS NULL 필터)
/jobs/{id} 단건 조회 시 404

Response: 200 + {"deleted": true}
404: Job not found (이미 삭제됨 포함)
```

## DB 스키마 변경

```sql
ALTER TABLE forge_jobs ADD COLUMN deleted_at TIMESTAMPTZ;
```

schema.sql에도 반영.

## 환경변수 추가

```
FORGE_API_KEY=        # 관리 API 인증 키 (빈 값이면 인증 비활성화)
```

## 파일 변경 요약

| 파일 | 변경 |
|------|------|
| `config.py` | `forge_api_key: str = ""` 추가 |
| `auth.py` | 신규 — API 키 인증 FastAPI Depends |
| `admin.py` | 신규 — 관리 API 라우터 (8개 엔드포인트) |
| `job_store.py` | list_jobs, get_full_job, update_meta, soft_delete, stats 쿼리 메서드 추가 |
| `app.py` | admin 라우터 마운트 |
| `schema.sql` | `deleted_at` 컬럼 추가 |
| `.env.example` | `FORGE_API_KEY` 추가 |
| `tests/test_admin.py` | 신규 — 관리 API 테스트 |
| `tests/test_auth.py` | 신규 — 인증 테스트 |

## 스코프 외

- 히스토리 아카이빙 테이블 (soft delete로 충분, 나중에 필요하면)
- 페이지네이션 커서 방식 (offset으로 시작, 규모 커지면 전환)
- VLM 로그 조회 API (대시보드에서 stats로 충분)
