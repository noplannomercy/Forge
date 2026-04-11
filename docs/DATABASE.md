# Forge 데이터베이스 구조

> 이 문서는 Forge가 사용하는 PostgreSQL 테이블, 인덱스, 스키마 관리 방식,
> Cortex와의 DB 공유 전략, 실무 쿼리 예시를 설명한다.

---

## DB 공유 전략

Forge와 Cortex는 **같은 PostgreSQL 인스턴스, 같은 데이터베이스(`hc_rag`)** 를 공유한다.
테이블 이름 prefix로 충돌을 방지한다.

```
hc_rag 데이터베이스
├── forge_jobs           ← Forge
├── forge_vlm_logs       ← Forge
├── forge_prompts        ← Forge
├── documents            ← Cortex
├── document_metadata    ← Cortex
├── document_sources     ← Cortex
├── memories             ← Cortex
├── edge_occurrence      ← Cortex
├── domain_rules         ← Cortex
├── search_logs          ← Cortex
└── cortex_graph (AGE)   ← Cortex
```

Forge는 `forge_` prefix 테이블만 읽고 쓴다. Cortex 테이블에 접근하지 않는다.

---

## 스키마 관리: Startup Auto-Apply

Forge가 기동할 때 `schema.sql`을 자동 실행한다.

```
app.py lifespan:
  1. asyncpg pool 생성
  2. _apply_schema(pool) → schema.sql 실행
  3. PromptStore seed (기본 프롬프트 없으면 생성)
  4. 앱 준비 완료
```

`schema.sql`의 모든 DDL은 `CREATE ... IF NOT EXISTS`, `ADD COLUMN IF NOT EXISTS`로 작성되어 있어서
매번 실행해도 안전하다 (idempotent). DB를 날려도 다음 기동에 자동 복구.

Cortex도 같은 패턴으로 자기 스키마를 lifespan에서 자동 적용한다.

---

## 연결 설정

| 환경 | DATABASE_URL |
|------|-------------|
| 비설정 (빈값) | InMemoryJobStore 사용 (DB 없음, 서버 끄면 데이터 소멸) |
| 로컬 개발 | `postgresql://postgres:postgres@localhost:5556/graphrag` |
| Docker integration | `postgresql://hc:hc_dev@postgres:5432/hc_rag` |
| AWS RDS | `postgresql://hc:XXX@rds-endpoint.region.rds.amazonaws.com:5432/hc_rag` |

연결은 `asyncpg.create_pool(DATABASE_URL)`로 비동기 커넥션 풀을 생성한다.
앱 종료 시 `pool.close()`로 정리.

---

## 테이블 상세

### forge_jobs — 변환 작업 레코드

모든 변환 요청의 입력/결과/상태를 저장하는 핵심 테이블.

```sql
CREATE TABLE IF NOT EXISTS forge_jobs (
    id              UUID PRIMARY KEY,
    file_name       VARCHAR(500) NOT NULL,
    file_size       BIGINT,
    source_format   VARCHAR(20) NOT NULL,     -- pdf, docx, pptx, xlsx, hwpx, jpg, png
    route           VARCHAR(20) NOT NULL,     -- extract, vlm
    method          VARCHAR(20) NOT NULL DEFAULT 'extract',  -- extract, semantic
    status          VARCHAR(20) NOT NULL DEFAULT 'queued',   -- queued, processing, completed, failed
    requested_by    VARCHAR(100),             -- 요청자 식별 (예: cortex, n8n-batch)
    result_text     TEXT,                     -- 변환 결과 마크다운 (완료 시)
    meta            JSONB DEFAULT '{}',       -- 자동 추출 메타데이터
    quality         JSONB DEFAULT '{}',       -- 품질 메트릭
    prompt_version      VARCHAR(50),          -- VLM 프롬프트 버전 (예: semantic-v2)
    meta_prompt_version VARCHAR(50),          -- 메타 추출 프롬프트 버전
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    started_at      TIMESTAMPTZ,             -- processing 시작 시각
    completed_at    TIMESTAMPTZ,             -- completed/failed 시각
    processing_ms   INT,                     -- 처리 소요시간 (밀리초)
    error           TEXT,                     -- 실패 시 에러 메시지
    deleted_at      TIMESTAMPTZ              -- soft delete (NULL이면 활성)
);
```

**컬럼별 설명:**

| 컬럼 | 설명 |
|------|------|
| `id` | UUID. 클라이언트가 `/result/{id}`로 조회 |
| `file_name` | 원본 파일명. 변환 후 원본 bytes는 버려지고 이름만 남음 |
| `file_size` | 업로드된 파일 크기 (bytes) |
| `source_format` | 원본 포맷 (pdf, docx, pptx, xlsx, hwpx, jpg, png, tiff, bmp) |
| `route` | 변환 경로. `extract` (텍스트 추출) 또는 `vlm` (비전 모델) |
| `method` | `extract` 또는 `semantic`. route와 비슷하지만 VLM 호출 방식을 명시 |
| `status` | `queued` → `processing` → `completed` 또는 `failed` |
| `requested_by` | 누가 요청했는지. `?requested_by=cortex-api` 쿼리파라미터로 전달 |
| `result_text` | 변환된 마크다운 전문. 수만 자 가능 |
| `meta` | LLM이 자동 추출한 메타데이터. JSONB. 예: `{"category":"...", "title":"..."}` |
| `quality` | 품질 메트릭. JSONB. `total_chars`, `confidence`, `failed_batches` 등 |
| `prompt_version` | 이 Job에 사용된 VLM 프롬프트 버전. 예: `semantic-v2` |
| `meta_prompt_version` | 메타 추출 프롬프트 버전. 예: `meta_extract-v1` |
| `processing_ms` | `completed_at - started_at` 밀리초. 성능 추적용 |
| `error` | 실패 시 예외 메시지. 성공 시 NULL |
| `deleted_at` | soft delete. NULL이면 활성. 값이 있으면 `/jobs` 목록에서 제외 |

**quality JSONB 예시:**
```json
{
  "total_chars": 63835,
  "chars_per_page": 997.4,
  "total_pages": 64,
  "failed_pages": 0,
  "confidence": "high",
  "total_batches": 13,
  "failed_batches": 0,
  "method": "semantic"
}
```

`confidence` 값: `high` (전체 성공), `partial` (일부 배치 실패), `low` (대부분 실패 또는 빈 결과).

---

### forge_vlm_logs — VLM 호출 로그

VLM 배치 호출마다 토큰/비용/지연시간을 기록하는 감사 테이블.

```sql
CREATE TABLE IF NOT EXISTS forge_vlm_logs (
    id              SERIAL PRIMARY KEY,
    job_id          UUID REFERENCES forge_jobs(id),
    batch_num       INT,              -- 이 Job의 몇 번째 배치인지
    purpose         VARCHAR(20),      -- 'convert' (향후 다른 용도 확장 가능)
    model           VARCHAR(100),     -- VLM 모델명
    prompt_version  VARCHAR(50),      -- 프롬프트 버전
    input_tokens    INT,              -- 입력 토큰 수
    output_tokens   INT,              -- 출력 토큰 수
    cost_usd        DECIMAL(10,6),    -- 비용 (USD, API 제공 시)
    latency_ms      INT,              -- 응답 소요시간 (밀리초)
    success         BOOLEAN,          -- 성공 여부
    error           TEXT,             -- 실패 시 에러 메시지
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
```

**활용:**
- `/stats/cost` — 일별 비용 집계
- `/stats/models` — 모델별 호출 수, 평균 지연시간, 총 토큰
- 프롬프트 버전별 성능 비교 (어떤 프롬프트가 더 좋은 결과를 냈는지)
- VLM 장애 분석 (어떤 배치가 실패했는지, 에러 메시지)

---

### forge_prompts — 프롬프트 버전 관리

VLM 프롬프트와 메타 추출 프롬프트를 DB에서 관리.
코드 배포 없이 프롬프트를 교체할 수 있게 해준다.

```sql
CREATE TABLE IF NOT EXISTS forge_prompts (
    id          SERIAL PRIMARY KEY,
    type        VARCHAR(30) NOT NULL,    -- 'semantic' 또는 'meta_extract'
    version     INT NOT NULL,            -- 자동 증가 (type 단위)
    text        TEXT NOT NULL,           -- 프롬프트 전문
    is_active   BOOLEAN DEFAULT TRUE,    -- 현재 사용 중인 버전인지
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
```

**type별 최대 1개만 active** (유니크 부분 인덱스로 보장):
```sql
CREATE UNIQUE INDEX IF NOT EXISTS idx_forge_prompts_active
    ON forge_prompts(type) WHERE is_active = TRUE;
```

**프롬프트 교체 흐름:**
```
1. POST /prompts {"type":"semantic", "text":"새 프롬프트"}
2. PromptStore가:
   a. 기존 semantic active를 is_active=FALSE로 변경
   b. 새 row 삽입 (version=기존+1, is_active=TRUE)
3. 다음 변환부터 새 프롬프트 사용
4. forge_vlm_logs에 prompt_version="semantic-v3" 기록
```

**seed 동작:** 서버 기동 시 해당 type의 프롬프트가 하나도 없으면 코드의 기본값으로 seed.
이미 있으면 건드리지 않음.

---

## 인덱스

```sql
-- forge_jobs 조회 최적화
CREATE INDEX idx_forge_jobs_status ON forge_jobs(status);
CREATE INDEX idx_forge_jobs_created ON forge_jobs(created_at DESC);
CREATE INDEX idx_forge_jobs_requested_by ON forge_jobs(requested_by);
CREATE INDEX idx_forge_jobs_meta ON forge_jobs USING GIN(meta);

-- forge_vlm_logs 집계 최적화
CREATE INDEX idx_forge_vlm_logs_job ON forge_vlm_logs(job_id);
CREATE INDEX idx_forge_vlm_logs_model ON forge_vlm_logs(model);

-- forge_prompts active 유니크 보장
CREATE UNIQUE INDEX idx_forge_prompts_active ON forge_prompts(type) WHERE is_active = TRUE;
```

| 인덱스 | 용도 |
|--------|------|
| `idx_forge_jobs_status` | `/jobs?status=completed` 필터링 |
| `idx_forge_jobs_created` | 최신순 정렬 |
| `idx_forge_jobs_requested_by` | 요청자별 조회 |
| `idx_forge_jobs_meta` | GIN 인덱스. JSONB 내부 검색 (`meta->>'category' = '...'`) |
| `idx_forge_vlm_logs_job` | 특정 Job의 배치 로그 조회 |
| `idx_forge_vlm_logs_model` | 모델별 통계 집계 |
| `idx_forge_prompts_active` | type당 active 1개 보장 (유니크 부분 인덱스) |

---

## 실무 쿼리 예시

### Job 현황 파악

```sql
-- 상태별 Job 수
SELECT status, COUNT(*) FROM forge_jobs
WHERE deleted_at IS NULL
GROUP BY status;

-- 최근 10건
SELECT id, file_name, status, source_format, processing_ms
FROM forge_jobs
WHERE deleted_at IS NULL
ORDER BY created_at DESC
LIMIT 10;

-- 실패한 Job 에러 확인
SELECT id, file_name, error, created_at
FROM forge_jobs
WHERE status = 'failed' AND deleted_at IS NULL
ORDER BY created_at DESC;
```

### 품질 분석

```sql
-- 포맷별 평균 변환 크기
SELECT source_format,
       COUNT(*) as jobs,
       ROUND(AVG((quality->>'total_chars')::int)) as avg_chars,
       ROUND(AVG(processing_ms)) as avg_ms
FROM forge_jobs
WHERE status = 'completed' AND deleted_at IS NULL
GROUP BY source_format;

-- confidence가 partial인 Job (일부 배치 실패)
SELECT id, file_name, quality->>'confidence' as confidence,
       quality->>'failed_batches' as failed
FROM forge_jobs
WHERE quality->>'confidence' = 'partial';
```

### 메타데이터 검색

```sql
-- 특정 카테고리의 문서
SELECT id, file_name, meta->>'category' as category,
       meta->>'title' as title
FROM forge_jobs
WHERE meta->>'category' LIKE '%거버넌스%'
AND deleted_at IS NULL;

-- 메타 추출이 안 된 Job
SELECT id, file_name, status
FROM forge_jobs
WHERE status = 'completed'
AND (meta IS NULL OR meta = '{}')
AND deleted_at IS NULL;
```

### VLM 비용/성능 분석

```sql
-- 일별 VLM 비용
SELECT DATE(created_at) as day,
       COUNT(*) as calls,
       SUM(input_tokens) as total_in,
       SUM(output_tokens) as total_out,
       SUM(cost_usd) as total_cost
FROM forge_vlm_logs
GROUP BY DATE(created_at)
ORDER BY day DESC;

-- 모델별 평균 지연시간
SELECT model,
       COUNT(*) as calls,
       ROUND(AVG(latency_ms)) as avg_latency,
       ROUND(AVG(input_tokens)) as avg_in_tokens
FROM forge_vlm_logs
WHERE success = true
GROUP BY model;

-- 실패 배치 분석
SELECT job_id, batch_num, error, created_at
FROM forge_vlm_logs
WHERE success = false
ORDER BY created_at DESC
LIMIT 20;
```

### 프롬프트 버전 확인

```sql
-- 현재 활성 프롬프트
SELECT type, version, LEFT(text, 100) as preview, created_at
FROM forge_prompts
WHERE is_active = true;

-- 프롬프트 변경 이력
SELECT type, version, is_active, created_at
FROM forge_prompts
ORDER BY type, version;

-- 특정 프롬프트 버전으로 변환된 Job 수
SELECT prompt_version, COUNT(*) as jobs
FROM forge_jobs
WHERE prompt_version IS NOT NULL
GROUP BY prompt_version
ORDER BY jobs DESC;
```

### 정리/유지보수

```sql
-- soft delete된 Job 수
SELECT COUNT(*) FROM forge_jobs WHERE deleted_at IS NOT NULL;

-- 30일 이상 지난 실패 Job 정리 (주의: 실행 전 확인)
-- UPDATE forge_jobs SET deleted_at = NOW()
-- WHERE status = 'failed'
-- AND created_at < NOW() - INTERVAL '30 days'
-- AND deleted_at IS NULL;

-- 테이블 크기 확인
SELECT relname as table,
       pg_size_pretty(pg_total_relation_size(relid)) as total_size
FROM pg_catalog.pg_statio_user_tables
WHERE relname LIKE 'forge_%'
ORDER BY pg_total_relation_size(relid) DESC;
```

---

## Docker에서 DB 직접 접근

```bash
# integration 모드 — infra compose의 postgres 컨테이너
docker exec hc-rag-postgres psql -U hc -d hc_rag

# 또는 호스트에서 (포트 5432 매핑 시)
psql -h localhost -p 5432 -U hc -d hc_rag
```

---

## InMemoryJobStore (개발용)

`DATABASE_URL`이 비어있으면 PostgreSQL 대신 InMemoryJobStore를 사용한다.
Python 딕셔너리에 Job을 저장하므로:

- 서버 끄면 데이터 전부 소멸
- 스키마 적용 불필요
- VLM 로그, 프롬프트 관리, 통계 기능 사용 불가
- 개발/테스트 편의용

프로덕션에서는 반드시 PostgreSQL 사용.
