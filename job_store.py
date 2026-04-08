import json
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone

from models import ConvertResult, Job, JobStatus, Quality


class JobStore(ABC):
    @abstractmethod
    async def create(self, file_name: str, source_format: str, route: str, **kwargs) -> Job: ...

    @abstractmethod
    async def get(self, job_id: str) -> Job | None: ...

    @abstractmethod
    async def update_status(self, job_id: str, status: JobStatus) -> None: ...

    @abstractmethod
    async def save_result(self, job_id: str, result: ConvertResult) -> None: ...

    @abstractmethod
    async def save_error(self, job_id: str, error: str) -> None: ...

    async def save_meta(self, job_id: str, meta: dict, meta_prompt_version: str | None = None) -> None:
        """기본 no-op. 구현체에서 오버라이드."""
        pass


class InMemoryJobStore(JobStore):
    def __init__(self):
        self._jobs: dict[str, Job] = {}

    async def create(self, file_name: str, source_format: str, route: str, **kwargs) -> Job:
        job = Job(
            id=str(uuid.uuid4()),
            status=JobStatus.QUEUED,
            file_name=file_name,
            source_format=source_format,
            route=route,
            **kwargs,
        )
        self._jobs[job.id] = job
        return job

    async def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    async def update_status(self, job_id: str, status: JobStatus) -> None:
        if job_id in self._jobs:
            self._jobs[job_id].status = status

    async def save_result(self, job_id: str, result: ConvertResult) -> None:
        if job_id in self._jobs:
            job = self._jobs[job_id]
            job.status = JobStatus.COMPLETED
            job.result = result
            job.completed_at = datetime.now(timezone.utc)

    async def save_meta(self, job_id: str, meta: dict, meta_prompt_version: str | None = None) -> None:
        if job_id in self._jobs:
            self._jobs[job_id].meta = meta
            self._jobs[job_id].meta_prompt_version = meta_prompt_version

    async def save_error(self, job_id: str, error: str) -> None:
        if job_id in self._jobs:
            job = self._jobs[job_id]
            job.status = JobStatus.FAILED
            job.error = error
            job.completed_at = datetime.now(timezone.utc)

    async def soft_delete(self, job_id: str) -> bool:
        if job_id in self._jobs:
            del self._jobs[job_id]
            return True
        return False


class PostgresJobStore(JobStore):
    def __init__(self, pool):
        self._pool = pool

    def _row_to_job(self, row: dict) -> Job:
        # result 재구성 (DB에서 읽을 때)
        result = None
        if row.get("result_text") is not None:
            quality_data = json.loads(row["quality"]) if isinstance(row["quality"], str) else (row["quality"] or {})
            result = ConvertResult(
                text=row["result_text"],
                format="md",
                pages=quality_data.get("total_pages", 0),
                file_name=row["file_name"],
                source_format=row["source_format"],
                route=row["route"],
                quality=Quality(**quality_data) if quality_data else Quality(
                    total_chars=0, chars_per_page=0, total_pages=0, failed_pages=0, confidence="unknown",
                ),
            )

        return Job(
            id=str(row["id"]),
            status=JobStatus(row["status"]),
            file_name=row["file_name"],
            file_size=row["file_size"],
            source_format=row["source_format"],
            route=row["route"],
            method=row.get("method", "extract"),
            requested_by=row["requested_by"],
            result=result,
            meta=json.loads(row["meta"]) if isinstance(row["meta"], str) else (row["meta"] or {}),
            prompt_version=row["prompt_version"],
            meta_prompt_version=row["meta_prompt_version"],
            error=row["error"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            processing_ms=row["processing_ms"],
        )

    async def create(self, file_name: str, source_format: str, route: str, **kwargs) -> Job:
        job_id = str(uuid.uuid4())
        file_size = kwargs.get("file_size")
        method = kwargs.get("method", "extract")
        requested_by = kwargs.get("requested_by")
        row = await self._pool.fetchrow(
            """INSERT INTO forge_jobs (id, file_name, file_size, source_format, route, method, status, requested_by)
               VALUES ($1, $2, $3, $4, $5, $6, 'queued', $7)
               RETURNING *""",
            job_id, file_name, file_size, source_format, route, method, requested_by,
        )
        return self._row_to_job(row)

    async def get(self, job_id: str) -> Job | None:
        row = await self._pool.fetchrow("SELECT * FROM forge_jobs WHERE id = $1 AND deleted_at IS NULL", job_id)
        if row is None:
            return None
        return self._row_to_job(row)

    async def update_status(self, job_id: str, status: JobStatus) -> None:
        if status == JobStatus.PROCESSING:
            await self._pool.execute(
                "UPDATE forge_jobs SET status = $1, started_at = NOW() WHERE id = $2",
                status.value, job_id,
            )
        else:
            await self._pool.execute(
                "UPDATE forge_jobs SET status = $1 WHERE id = $2",
                status.value, job_id,
            )

    async def save_result(self, job_id: str, result: ConvertResult) -> None:
        await self._pool.execute(
            """UPDATE forge_jobs
               SET status = 'completed', result_text = $1, quality = $2,
                   completed_at = NOW(), processing_ms = EXTRACT(EPOCH FROM (NOW() - COALESCE(started_at, created_at))) * 1000
               WHERE id = $3""",
            result.text, json.dumps(result.quality.model_dump()), job_id,
        )

    async def save_meta(self, job_id: str, meta: dict, meta_prompt_version: str | None = None) -> None:
        await self._pool.execute(
            "UPDATE forge_jobs SET meta = $1, meta_prompt_version = $2 WHERE id = $3",
            json.dumps(meta), meta_prompt_version, job_id,
        )

    async def save_error(self, job_id: str, error: str) -> None:
        await self._pool.execute(
            """UPDATE forge_jobs
               SET status = 'failed', error = $1,
                   completed_at = NOW(), processing_ms = EXTRACT(EPOCH FROM (NOW() - COALESCE(started_at, created_at))) * 1000
               WHERE id = $2""",
            error, job_id,
        )

    async def list_jobs(
        self, page: int = 1, size: int = 20,
        status: str | None = None, source_format: str | None = None,
        requested_by: str | None = None,
    ) -> tuple[list[dict], int]:
        conditions = ["deleted_at IS NULL"]
        params = []
        idx = 1
        if status:
            conditions.append(f"status = ${idx}")
            params.append(status)
            idx += 1
        if source_format:
            conditions.append(f"source_format = ${idx}")
            params.append(source_format)
            idx += 1
        if requested_by:
            conditions.append(f"requested_by = ${idx}")
            params.append(requested_by)
            idx += 1
        where = " AND ".join(conditions)
        total = await self._pool.fetchval(f"SELECT COUNT(*) FROM forge_jobs WHERE {where}", *params)
        offset = (page - 1) * size
        rows = await self._pool.fetch(
            f"""SELECT id, file_name, status, route, method, source_format,
                       requested_by, meta, processing_ms, created_at, deleted_at
                FROM forge_jobs WHERE {where}
                ORDER BY created_at DESC LIMIT ${idx} OFFSET ${idx + 1}""",
            *params, size, offset,
        )
        jobs = []
        for row in rows:
            meta = row["meta"]
            if isinstance(meta, str):
                meta = json.loads(meta)
            jobs.append({
                "id": str(row["id"]),
                "file_name": row["file_name"],
                "status": row["status"],
                "route": row["route"],
                "method": row["method"],
                "source_format": row["source_format"],
                "requested_by": row["requested_by"],
                "meta": meta or {},
                "processing_ms": row["processing_ms"],
                "created_at": str(row["created_at"]),
            })
        return jobs, total

    async def soft_delete(self, job_id: str) -> bool:
        result = await self._pool.execute(
            "UPDATE forge_jobs SET deleted_at = NOW() WHERE id = $1 AND deleted_at IS NULL", job_id,
        )
        return result == "UPDATE 1"

    async def update_meta(self, job_id: str, meta_patch: dict) -> dict:
        existing = await self._pool.fetchval("SELECT meta FROM forge_jobs WHERE id = $1 AND deleted_at IS NULL", job_id)
        if existing is None:
            return {}
        current = json.loads(existing) if isinstance(existing, str) else (existing or {})
        current.update(meta_patch)
        await self._pool.execute(
            "UPDATE forge_jobs SET meta = $1 WHERE id = $2", json.dumps(current), job_id,
        )
        return current

    async def stats_daily(self, from_date: str, to_date: str) -> list[dict]:
        rows = await self._pool.fetch(
            """SELECT DATE(created_at) AS day, COUNT(*) AS total,
                      COUNT(*) FILTER (WHERE status = 'completed') AS success,
                      COUNT(*) FILTER (WHERE status = 'failed') AS failed,
                      AVG(processing_ms) AS avg_ms
               FROM forge_jobs
               WHERE created_at >= $1::date AND created_at < $2::date + 1 AND deleted_at IS NULL
               GROUP BY DATE(created_at) ORDER BY day""",
            from_date, to_date,
        )
        return [dict(r) for r in rows]

    async def stats_cost(self, from_date: str, to_date: str) -> list[dict]:
        rows = await self._pool.fetch(
            """SELECT DATE(l.created_at) AS day,
                      COALESCE(SUM(l.cost_usd), 0) AS total_cost_usd,
                      COALESCE(SUM(COALESCE(l.input_tokens, 0) + COALESCE(l.output_tokens, 0)), 0) AS total_tokens
               FROM forge_vlm_logs l JOIN forge_jobs j ON l.job_id = j.id
               WHERE l.created_at >= $1::date AND l.created_at < $2::date + 1 AND j.deleted_at IS NULL
               GROUP BY DATE(l.created_at) ORDER BY day""",
            from_date, to_date,
        )
        return [dict(r) for r in rows]

    async def stats_models(self) -> list[dict]:
        rows = await self._pool.fetch(
            """SELECT model, COUNT(*) AS calls, AVG(latency_ms) AS avg_latency_ms,
                      COALESCE(SUM(cost_usd), 0) AS total_cost_usd,
                      COALESCE(SUM(input_tokens), 0) AS total_input_tokens,
                      COALESCE(SUM(output_tokens), 0) AS total_output_tokens
               FROM forge_vlm_logs GROUP BY model ORDER BY calls DESC"""
        )
        return [dict(r) for r in rows]


class VLMLogStore:
    def __init__(self, pool):
        self._pool = pool

    async def log(
        self, job_id: str, batch_num: int, purpose: str,
        model: str, prompt_version: str | None,
        input_tokens: int | None, output_tokens: int | None,
        cost_usd: float | None, latency_ms: int | None,
        success: bool, error: str | None,
    ) -> None:
        await self._pool.execute(
            """INSERT INTO forge_vlm_logs
               (job_id, batch_num, purpose, model, prompt_version,
                input_tokens, output_tokens, cost_usd, latency_ms, success, error)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)""",
            job_id, batch_num, purpose, model, prompt_version,
            input_tokens, output_tokens, cost_usd, latency_ms, success, error,
        )
