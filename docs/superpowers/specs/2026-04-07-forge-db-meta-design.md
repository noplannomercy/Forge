# Forge DB + LLM 메타 추출 — Design Spec

> 2026-04-07 | Forge v3 기반 설계

## 배경

Forge v2까지는 InMemoryJobStore로 동작하여 서버 재시작 시 모든 Job이 사라지고, 운영 메타데이터(비용, 처리 시간, 성공률)를 추적할 수 없었다. 백오피스/대시보드 구축이 불가능한 상태.

또한 변환된 텍스트에서 문서의 카테고리, 고객, 키워드 등 메타데이터를 자동으로 추출하면 운영자가 수동으로 태깅할 필요가 없어진다.

## 목표

1. Job 이력 + 변환 결과 + VLM 호출 로그를 PostgreSQL에 영속 저장
2. 변환 완료 후 LLM으로 문서 메타데이터를 자동 추출하여 JSONB에 저장
3. 백오피스 대시보드에 필요한 모든 데이터를 쿼리 가능하게

## 설계 결정사항

| 결정 | 선택 | 이유 |
|------|------|------|
| DB 위치 | Cortex PostgreSQL에 forge_ 스키마 | 인프라 단순화, 코드 독립성은 스키마 분리로 유지 |
| 변환 결과 저장 | DB TEXT 컬럼 | 최대 50KB 수준, 검색/미리보기에 DB가 유리 |
| 원본 파일 | Forge 관리 대상 아님 | 호출자가 관리, Forge는 file_bytes 받아서 처리만 |
| 동적 메타 | JSONB 컬럼 + LLM 자동 추출 | 파일 넣으면 LLM이 내용 분석해서 자동 태깅 |
| 메타 추출 모델 | 별도 설정 가능, 기본은 VLM fallback | 파라미터 작은 저렴한 모델로 충분 |
| 메타 추출 실패 | meta={}, job은 completed 유지 | 변환 결과는 버리지 않음 |
| InMemoryJobStore | 테스트용으로 유지 | PostgresJobStore가 프로덕션용 |

## DB 스키마

```sql
-- Cortex PostgreSQL, forge_ 접두사

CREATE TABLE forge_jobs (
    id              UUID PRIMARY KEY,
    file_name       VARCHAR(500) NOT NULL,
    file_size       BIGINT,
    source_format   VARCHAR(20) NOT NULL,
    route           VARCHAR(20) NOT NULL,       -- extract | vlm
    method          VARCHAR(20) NOT NULL,       -- extract | semantic
    status          VARCHAR(20) NOT NULL,       -- queued | processing | completed | failed

    -- 호출자
    requested_by    VARCHAR(100),

    -- 변환 결과
    result_text     TEXT,

    -- LLM 자동 추출 메타
    meta            JSONB DEFAULT '{}',

    -- quality
    quality         JSONB DEFAULT '{}',

    -- 프롬프트 버전
    prompt_version      VARCHAR(50),            -- "semantic-v1" 등
    meta_prompt_version VARCHAR(50),            -- 메타 추출 프롬프트 버전

    -- 시간
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    processing_ms   INT,

    -- 에러
    error           TEXT
);

CREATE TABLE forge_vlm_logs (
    id              SERIAL PRIMARY KEY,
    job_id          UUID REFERENCES forge_jobs(id),
    batch_num       INT,
    purpose         VARCHAR(20),                -- "convert" | "meta_extract"
    model           VARCHAR(100),
    prompt_version  VARCHAR(50),
    input_tokens    INT,
    output_tokens   INT,
    cost_usd        DECIMAL(10,6),
    latency_ms      INT,
    success         BOOLEAN,
    error           TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- 일별 집계 (materialized view)
CREATE MATERIALIZED VIEW forge_daily_stats AS
SELECT
    DATE(created_at) AS day,
    COUNT(*) AS total_jobs,
    COUNT(*) FILTER (WHERE status = 'completed') AS success_count,
    COUNT(*) FILTER (WHERE status = 'failed') AS fail_count,
    AVG(processing_ms) AS avg_processing_ms,
    SUM(cost_usd) AS total_cost_usd
FROM forge_jobs j
LEFT JOIN (
    SELECT job_id, SUM(cost_usd) AS cost_usd
    FROM forge_vlm_logs
    GROUP BY job_id
) v ON j.id = v.job_id
GROUP BY DATE(created_at);

-- 인덱스
CREATE INDEX idx_forge_jobs_status ON forge_jobs(status);
CREATE INDEX idx_forge_jobs_meta ON forge_jobs USING GIN(meta);
CREATE INDEX idx_forge_jobs_created ON forge_jobs(created_at DESC);
CREATE INDEX idx_forge_jobs_requested_by ON forge_jobs(requested_by);
CREATE INDEX idx_forge_vlm_logs_job ON forge_vlm_logs(job_id);
CREATE INDEX idx_forge_vlm_logs_model ON forge_vlm_logs(model);
```

## 처리 흐름

```
POST /convert (file, requested_by?)
  → router: 경로 결정
  → DB: forge_jobs INSERT (status=processing, started_at=now)
  → worker: 변환 처리
      → forge_vlm_logs INSERT (배치별, purpose=convert)
  → worker: 메타 추출 LLM 호출
      → forge_vlm_logs INSERT (purpose=meta_extract)
  → DB: forge_jobs UPDATE (status=completed, result_text, meta, quality, processing_ms)

GET /result/{job_id}
  → DB에서 직접 조회

GET /result/{job_id}?format=text
  → result_text만 plain text 반환 (Content-Type: text/markdown)
```

## 메타 추출

변환 완료 후 result_text를 LLM에 보내서 메타 자동 추출.

### 프롬프트

```
이 문서를 분석해서 JSON으로 메타데이터를 추출해.

반드시 포함: category, title, summary(2줄), keywords(5개)
가능하면 포함: client, author, date, budget, project_name

JSON만 반환. 다른 텍스트 없이.
```

### 입력

- result_text (길면 앞 3000자만 전송하여 토큰 절약)

### 출력 예시

```json
{
  "category": "제안서",
  "title": "안산시 강소형 스마트도시 조성사업",
  "summary": "안산시 원곡동 일원에 상호문화 플랫폼 기반 스마트도시를 조성하는 사업. 2025~2027년 160억 규모.",
  "keywords": ["스마트도시", "안산시", "상호문화", "IoT", "데이터허브"],
  "client": "안산시청",
  "budget": "160억",
  "project_name": "강소형 스마트도시 조성사업"
}
```

### 실패 처리

메타 추출 실패 시 `meta = {}`, job status는 completed 유지. 변환 결과는 보존.

## 환경변수 추가

```
# DB
DATABASE_URL=postgresql://user:pass@localhost:5432/cortex

# 메타 추출 LLM (미설정 시 VLM 설정 fallback)
META_LLM_URL=
META_LLM_MODEL=
META_LLM_API_KEY=
```

## API 변경

### `POST /convert`
- 추가: `requested_by` 파라미터 (optional)

### `GET /result/{job_id}`
- 기존 JSON 응답에 `meta` 필드 추가

### `GET /result/{job_id}?format=text`
- 신규: result_text만 `text/markdown`으로 반환

## JobStore 변경

- `InMemoryJobStore` — 테스트용으로 유지
- `PostgresJobStore` — 신규, 프로덕션용. JobStore ABC 구현
- `VLMLogStore` — 신규, forge_vlm_logs CRUD

## 파일 변경 요약

| 파일 | 변경 |
|------|------|
| `config.py` | DATABASE_URL, META_LLM_* 추가 |
| `models.py` | Job에 meta, requested_by, prompt_version 등 추가 |
| `job_store.py` | PostgresJobStore 구현 추가 |
| `worker.py` | 변환 후 메타 추출 단계 추가, vlm_logs 기록 |
| `vlm.py` | 토큰/비용 정보 반환하도록 BatchResult 확장 |
| `meta.py` | 신규 — 메타 추출 LLM 클라이언트 |
| `app.py` | requested_by 파라미터, ?format=text 응답, DB 연결 |
| `requirements.txt` | asyncpg 추가 |
| `.env.example` | DATABASE_URL, META_LLM_* 추가 |
| `schema.sql` | 신규 — DDL 스크립트 |

## 백오피스 쿼리 가능 목록

| 대시보드 항목 | 쿼리 소스 |
|--------------|----------|
| 일별/월별 변환 건수 | forge_daily_stats 또는 forge_jobs.created_at |
| 포맷별 처리 현황 | source_format |
| 성공/실패율 | status |
| 평균 처리 시간 | processing_ms |
| VLM 비용 추적 | forge_vlm_logs.cost_usd |
| 모델별 성능 비교 | forge_vlm_logs.model + latency_ms |
| 카테고리별 문서 분포 | meta->>'category' (GIN 인덱스) |
| 고객별 문서 현황 | meta->>'client' |
| 사용자별 사용량 | requested_by |
| 변환 결과 미리보기 | result_text |
| 프롬프트 버전별 비교 | prompt_version |
| 배치별 지연 분석 | forge_vlm_logs.batch_num + latency_ms |

## 스코프 외

- 백오피스 UI 구현 (이 스펙은 DB + API까지만)
- 프롬프트 관리 UI (환경변수/코드로 관리)
- 원본 파일 저장/관리 (Forge 관리 대상 아님)
- Redis 전환 (별도 스펙)
