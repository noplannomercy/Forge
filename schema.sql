-- schema.sql
-- Forge DB schema (Cortex PostgreSQL, forge_ 접두사)

CREATE TABLE IF NOT EXISTS forge_jobs (
    id              UUID PRIMARY KEY,
    file_name       VARCHAR(500) NOT NULL,
    file_size       BIGINT,
    source_format   VARCHAR(20) NOT NULL,
    route           VARCHAR(20) NOT NULL,
    method          VARCHAR(20) NOT NULL DEFAULT 'extract',
    status          VARCHAR(20) NOT NULL DEFAULT 'queued',
    requested_by    VARCHAR(100),
    result_text     TEXT,
    meta            JSONB DEFAULT '{}',
    quality         JSONB DEFAULT '{}',
    prompt_version      VARCHAR(50),
    meta_prompt_version VARCHAR(50),
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    processing_ms   INT,
    error           TEXT,
    deleted_at      TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS forge_vlm_logs (
    id              SERIAL PRIMARY KEY,
    job_id          UUID REFERENCES forge_jobs(id),
    batch_num       INT,
    purpose         VARCHAR(20),
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

CREATE INDEX IF NOT EXISTS idx_forge_jobs_status ON forge_jobs(status);
CREATE INDEX IF NOT EXISTS idx_forge_jobs_meta ON forge_jobs USING GIN(meta);
CREATE INDEX IF NOT EXISTS idx_forge_jobs_created ON forge_jobs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_forge_jobs_requested_by ON forge_jobs(requested_by);
CREATE INDEX IF NOT EXISTS idx_forge_vlm_logs_job ON forge_vlm_logs(job_id);
CREATE INDEX IF NOT EXISTS idx_forge_vlm_logs_model ON forge_vlm_logs(model);

-- 마이그레이션: 기존 테이블에 deleted_at 추가
ALTER TABLE forge_jobs ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;
