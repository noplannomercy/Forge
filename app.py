import asyncio
import logging
from typing import List

from fastapi import FastAPI, File, HTTPException, UploadFile

from config import Config
from job_store import InMemoryJobStore, JobStore
from router import UnsupportedFormatError, detect_route
from worker import process_job

logger = logging.getLogger(__name__)


async def _safe_process(job, file_bytes, route, store, config):
    """create_task용 래퍼. 미처리 예외를 로깅."""
    try:
        await process_job(job, file_bytes, route, store, config)
    except Exception:
        logger.exception("Unhandled error in job %s", job.id)


def create_app(store: JobStore | None = None, config: Config | None = None) -> FastAPI:
    config = config or Config()
    store = store or InMemoryJobStore()

    app = FastAPI(title="Forge — Document Converter", version="0.1.0")

    app.state.store = store
    app.state.config = config

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.post("/convert")
    async def convert(file: UploadFile = File(...)):
        file_bytes = await file.read()
        file_name = file.filename or "unknown"

        if len(file_bytes) > config.max_file_size:
            raise HTTPException(status_code=413, detail=f"File too large: max {config.max_file_size} bytes")

        try:
            route, source_format = detect_route(file_name, file_bytes)
        except UnsupportedFormatError as e:
            raise HTTPException(status_code=400, detail=str(e))

        job = await store.create(file_name, source_format, route)
        asyncio.create_task(_safe_process(job, file_bytes, route, store, config))

        return {"job_id": job.id, "status": job.status}

    @app.get("/result/{job_id}")
    async def result(job_id: str):
        job = await store.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")

        return {
            "status": job.status,
            "result": job.result.model_dump() if job.result else None,
            "error": job.error,
        }

    @app.post("/batch")
    async def batch(files: List[UploadFile] = File(...)):
        jobs = []
        for file in files:
            file_bytes = await file.read()
            file_name = file.filename or "unknown"

            if len(file_bytes) > config.max_file_size:
                jobs.append({"file_name": file_name, "error": f"File too large: max {config.max_file_size} bytes"})
                continue

            try:
                route, source_format = detect_route(file_name, file_bytes)
            except UnsupportedFormatError as e:
                jobs.append({"file_name": file_name, "error": str(e)})
                continue

            job = await store.create(file_name, source_format, route)
            asyncio.create_task(_safe_process(job, file_bytes, route, store, config))
            jobs.append({"file_name": file_name, "job_id": job.id, "status": job.status})

        return {"jobs": jobs}

    return app


app = create_app()
