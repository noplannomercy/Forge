import asyncio
import logging
from contextlib import asynccontextmanager
from typing import List

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import PlainTextResponse

from config import Config
from job_store import InMemoryJobStore, JobStore
from router import UnsupportedFormatError, detect_route
from worker import process_job

logger = logging.getLogger(__name__)


async def _safe_process(job, file_bytes, route, store, config, meta_extractor=None, vlm_log_store=None):
    """create_task용 래퍼. 미처리 예외를 로깅."""
    try:
        await process_job(job, file_bytes, route, store, config, meta_extractor=meta_extractor, vlm_log_store=vlm_log_store)
    except Exception:
        logger.exception("Unhandled error in job %s", job.id)


def create_app(store: JobStore | None = None, config: Config | None = None) -> FastAPI:
    config = config or Config()
    store = store or InMemoryJobStore()

    @asynccontextmanager
    async def lifespan(a):
        # startup
        a.state.store = store
        a.state.config = config
        if config.database_url:
            import asyncpg
            from job_store import PostgresJobStore, VLMLogStore
            pool = await asyncpg.create_pool(config.database_url)
            a.state.pool = pool
            a.state.store = PostgresJobStore(pool)
            a.state.vlm_log_store = VLMLogStore(pool)
        from meta import MetaExtractor
        a.state.meta_extractor = MetaExtractor(config)

        yield

        # shutdown
        if hasattr(a.state, "pool"):
            await a.state.pool.close()
        if hasattr(a.state, "meta_extractor"):
            await a.state.meta_extractor.close()

    app = FastAPI(title="Forge — Document Converter", version="0.3.0", lifespan=lifespan)

    # 테스트 등 lifespan 미실행 환경을 위한 기본값
    app.state.store = store
    app.state.config = config

    from auth import verify_api_key
    from admin import create_admin_router

    auth_dep = verify_api_key(config)
    admin_router = create_admin_router(app.state, auth_dep)
    app.include_router(admin_router)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.post("/convert")
    async def convert(
        file: UploadFile = File(...),
        route: str | None = Query(None, pattern="^(extract|vlm)$"),
        requested_by: str | None = Query(None),
    ):
        file_bytes = await file.read()
        file_name = file.filename or "unknown"

        if len(file_bytes) > config.max_file_size:
            raise HTTPException(status_code=413, detail=f"File too large: max {config.max_file_size} bytes")

        try:
            detected_route, source_format = detect_route(file_name, file_bytes, route_override=route)
        except UnsupportedFormatError as e:
            raise HTTPException(status_code=400, detail=str(e))

        method = "semantic" if detected_route == "vlm" else "extract"
        current_store = app.state.store
        job = await current_store.create(
            file_name, source_format, detected_route,
            file_size=len(file_bytes), method=method, requested_by=requested_by,
        )
        meta_ext = getattr(app.state, "meta_extractor", None)
        vlm_logs = getattr(app.state, "vlm_log_store", None)
        asyncio.create_task(_safe_process(job, file_bytes, detected_route, current_store, config, meta_extractor=meta_ext, vlm_log_store=vlm_logs))

        return {"job_id": job.id, "status": job.status}

    @app.get("/result/{job_id}")
    async def result(
        job_id: str,
        format: str | None = Query(None, alias="format"),
    ):
        current_store = app.state.store
        job = await current_store.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")

        if format == "text" and job.result:
            return PlainTextResponse(
                content=job.result.text,
                media_type="text/markdown",
            )

        return {
            "status": job.status,
            "result": job.result.model_dump() if job.result else None,
            "meta": getattr(job, "meta", {}),
            "error": job.error,
        }

    @app.post("/batch")
    async def batch(
        files: List[UploadFile] = File(...),
        route: str | None = Query(None, pattern="^(extract|vlm)$"),
        requested_by: str | None = Query(None),
    ):
        jobs = []
        current_store = app.state.store
        for file in files:
            file_bytes = await file.read()
            file_name = file.filename or "unknown"

            if len(file_bytes) > config.max_file_size:
                jobs.append({"file_name": file_name, "error": f"File too large: max {config.max_file_size} bytes"})
                continue

            try:
                detected_route, source_format = detect_route(file_name, file_bytes, route_override=route)
            except UnsupportedFormatError as e:
                jobs.append({"file_name": file_name, "error": str(e)})
                continue

            method = "semantic" if detected_route == "vlm" else "extract"
            job = await current_store.create(
                file_name, source_format, detected_route,
                file_size=len(file_bytes), method=method, requested_by=requested_by,
            )
            meta_ext = getattr(app.state, "meta_extractor", None)
            asyncio.create_task(_safe_process(job, file_bytes, detected_route, current_store, config, meta_extractor=meta_ext))
            jobs.append({"file_name": file_name, "job_id": job.id, "status": job.status})

        return {"jobs": jobs}

    return app


app = create_app()
