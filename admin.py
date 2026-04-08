from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query


def create_admin_router(app_state, auth_dep) -> APIRouter:
    router = APIRouter(dependencies=[Depends(auth_dep)])

    @router.get("/jobs")
    async def list_jobs(
        status: str | None = Query(None),
        source_format: str | None = Query(None),
        requested_by: str | None = Query(None),
        page: int = Query(1, ge=1),
        size: int = Query(20, ge=1, le=100),
    ):
        store = app_state.store
        if not hasattr(store, "list_jobs"):
            raise HTTPException(status_code=501, detail="list_jobs not supported (InMemoryJobStore)")
        jobs, total = await store.list_jobs(
            page=page, size=size,
            status=status, source_format=source_format, requested_by=requested_by,
        )
        return {"jobs": jobs, "total": total, "page": page, "size": size}

    @router.get("/jobs/{job_id}")
    async def get_job(job_id: str):
        store = app_state.store
        job = await store.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return {
            "id": job.id,
            "file_name": job.file_name,
            "file_size": job.file_size,
            "status": job.status,
            "route": job.route,
            "method": job.method,
            "source_format": job.source_format,
            "requested_by": job.requested_by,
            "result_text": job.result.text if job.result else None,
            "meta": job.meta,
            "quality": job.result.quality.model_dump() if job.result else None,
            "prompt_version": job.prompt_version,
            "meta_prompt_version": job.meta_prompt_version,
            "processing_ms": job.processing_ms,
            "created_at": str(job.created_at),
            "started_at": str(job.started_at) if job.started_at else None,
            "completed_at": str(job.completed_at) if job.completed_at else None,
            "error": job.error,
        }

    @router.patch("/jobs/{job_id}/meta")
    async def patch_meta(job_id: str, body: dict):
        store = app_state.store
        job = await store.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        if hasattr(store, "update_meta"):
            merged = await store.update_meta(job_id, body)
        else:
            job.meta.update(body)
            merged = job.meta
        return {"meta": merged}

    @router.post("/jobs/{job_id}/retry")
    async def retry_meta(job_id: str):
        store = app_state.store
        job = await store.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        if not job.result:
            raise HTTPException(status_code=400, detail="Job has no result yet")
        meta_extractor = getattr(app_state, "meta_extractor", None)
        if meta_extractor is None:
            raise HTTPException(status_code=503, detail="MetaExtractor not available")
        meta = await meta_extractor.extract(job.result.text)
        from worker import META_PROMPT_VERSION
        await store.save_meta(job_id, meta, META_PROMPT_VERSION)
        return {"meta": meta}

    @router.delete("/jobs/{job_id}")
    async def delete_job(job_id: str):
        store = app_state.store
        if hasattr(store, "soft_delete"):
            deleted = await store.soft_delete(job_id)
        else:
            deleted = False
        if not deleted:
            raise HTTPException(status_code=404, detail="Job not found")
        return {"deleted": True}

    @router.get("/stats/daily")
    async def stats_daily(
        from_date: str | None = Query(None, alias="from"),
        to_date: str | None = Query(None, alias="to"),
    ):
        store = app_state.store
        if not hasattr(store, "stats_daily"):
            raise HTTPException(status_code=501, detail="stats not supported")
        f = from_date or str(date.today() - timedelta(days=7))
        t = to_date or str(date.today())
        stats = await store.stats_daily(f, t)
        return {"stats": stats}

    @router.get("/stats/cost")
    async def stats_cost(
        from_date: str | None = Query(None, alias="from"),
        to_date: str | None = Query(None, alias="to"),
    ):
        store = app_state.store
        if not hasattr(store, "stats_cost"):
            raise HTTPException(status_code=501, detail="stats not supported")
        f = from_date or str(date.today() - timedelta(days=7))
        t = to_date or str(date.today())
        stats = await store.stats_cost(f, t)
        return {"stats": stats}

    @router.get("/stats/models")
    async def stats_models():
        store = app_state.store
        if not hasattr(store, "stats_models"):
            raise HTTPException(status_code=501, detail="stats not supported")
        stats = await store.stats_models()
        return {"models": stats}

    return router
