import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone

from models import ConvertResult, Job, JobStatus


class JobStore(ABC):
    @abstractmethod
    async def create(self, file_name: str, source_format: str, route: str) -> Job: ...

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

    async def create(self, file_name: str, source_format: str, route: str) -> Job:
        job = Job(
            id=str(uuid.uuid4()),
            status=JobStatus.QUEUED,
            file_name=file_name,
            source_format=source_format,
            route=route,
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

    async def save_error(self, job_id: str, error: str) -> None:
        if job_id in self._jobs:
            job = self._jobs[job_id]
            job.status = JobStatus.FAILED
            job.error = error
            job.completed_at = datetime.now(timezone.utc)
