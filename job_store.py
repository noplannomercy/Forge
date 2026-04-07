import json
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone

from models import ConvertResult, Job, JobStatus


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


class PostgresJobStore(JobStore):
    def __init__(self, pool):
        self._pool = pool

    def _row_to_job(self, row: dict) -> Job:
        return Job(
            id=str(row["id"]),
            status=JobStatus(row["status"]),
            file_name=row["file_name"],
            file_size=row["file_size"],
            source_format=row["source_format"],
            route=row["route"],
            method=row.get("method", "extract"),
            requested_by=row["requested_by"],
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
        row = await self._pool.fetchrow("SELECT * FROM forge_jobs WHERE id = $1", job_id)
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
