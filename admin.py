from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query


def create_admin_router(app_state, auth_dep) -> APIRouter:
    router = APIRouter(dependencies=[Depends(auth_dep)], tags=["관리"])

    @router.get("/jobs", summary="Job 목록 조회")
    async def list_jobs(
        status: str | None = Query(None, description="필터: queued, processing, completed, failed"),
        source_format: str | None = Query(None, description="필터: pdf, docx, pptx, xlsx 등"),
        requested_by: str | None = Query(None, description="필터: 요청자"),
        page: int = Query(1, ge=1, description="페이지 번호"),
        size: int = Query(20, ge=1, le=100, description="페이지 크기 (최대 100)"),
    ):
        """Job 목록 조회. 필터 + 페이징. result_text는 목록에서 제외 (무거움)."""
        store = app_state.store
        if not hasattr(store, "list_jobs"):
            raise HTTPException(status_code=501, detail="list_jobs not supported (InMemoryJobStore)")
        jobs, total = await store.list_jobs(
            page=page, size=size,
            status=status, source_format=source_format, requested_by=requested_by,
        )
        return {"jobs": jobs, "total": total, "page": page, "size": size}

    @router.get("/jobs/{job_id}", summary="Job 단건 상세")
    async def get_job(job_id: str):
        """Job 전체 필드 반환. result_text, meta, quality 포함."""
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

    @router.patch("/jobs/{job_id}/meta", summary="메타 수정 (merge)")
    async def patch_meta(job_id: str, body: dict):
        """기존 meta에 전달된 필드를 merge. LLM 자동 추출이 틀렸을 때 수동 보정용."""
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

    @router.post("/jobs/{job_id}/retry", summary="메타 재추출")
    async def retry_meta(job_id: str):
        """result_text를 기반으로 LLM 메타 추출을 다시 실행. 모델/프롬프트 변경 후 재시도용."""
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

    @router.delete("/jobs/{job_id}", summary="Job 삭제 (soft delete)")
    async def delete_job(job_id: str):
        """deleted_at 타임스탬프 기록. 목록/조회에서 제외되지만 DB에는 보존."""
        store = app_state.store
        if hasattr(store, "soft_delete"):
            deleted = await store.soft_delete(job_id)
        else:
            deleted = False
        if not deleted:
            raise HTTPException(status_code=404, detail="Job not found")
        return {"deleted": True}

    @router.get("/stats/daily", summary="일별 변환 통계")
    async def stats_daily(
        from_date: str | None = Query(None, alias="from", description="시작일 (YYYY-MM-DD, 기본 7일 전)"),
        to_date: str | None = Query(None, alias="to", description="종료일 (YYYY-MM-DD, 기본 오늘)"),
    ):
        """일별 총 건수, 성공, 실패, 평균 처리시간."""
        store = app_state.store
        if not hasattr(store, "stats_daily"):
            raise HTTPException(status_code=501, detail="stats not supported")
        f = from_date or str(date.today() - timedelta(days=7))
        t = to_date or str(date.today())
        stats = await store.stats_daily(f, t)
        return {"stats": stats}

    @router.get("/stats/cost", summary="VLM 비용 집계")
    async def stats_cost(
        from_date: str | None = Query(None, alias="from", description="시작일 (YYYY-MM-DD)"),
        to_date: str | None = Query(None, alias="to", description="종료일 (YYYY-MM-DD)"),
    ):
        """일별 VLM 호출 비용 + 토큰 합계."""
        store = app_state.store
        if not hasattr(store, "stats_cost"):
            raise HTTPException(status_code=501, detail="stats not supported")
        f = from_date or str(date.today() - timedelta(days=7))
        t = to_date or str(date.today())
        stats = await store.stats_cost(f, t)
        return {"stats": stats}

    @router.get("/stats/models", summary="모델별 사용량")
    async def stats_models():
        """모델별 호출 수, 평균 지연, 총 비용, 토큰 합계."""
        store = app_state.store
        if not hasattr(store, "stats_models"):
            raise HTTPException(status_code=501, detail="stats not supported")
        stats = await store.stats_models()
        return {"models": stats}

    return router
