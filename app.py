import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import List

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import PlainTextResponse

from config import Config
from job_store import InMemoryJobStore, JobStore
from models import RefineResponse
from refine import Refiner
from router import UnsupportedFormatError, detect_route
from worker import process_job

logger = logging.getLogger(__name__)

SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")


async def _apply_schema(pool) -> None:
    """schema.sql을 startup 시 적용. 모든 DDL이 IF NOT EXISTS라 idempotent."""
    if not os.path.isfile(SCHEMA_PATH):
        logger.warning("schema.sql not found at %s, skipping auto-apply", SCHEMA_PATH)
        return
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        ddl = f.read()
    async with pool.acquire() as conn:
        await conn.execute(ddl)
    logger.info("schema.sql applied successfully")


async def _safe_process(job, file_bytes, route, store, config, meta_extractor=None, vlm_log_store=None, prompts=None, revdoc_generator=None):
    """create_task용 래퍼. 미처리 예외를 로깅."""
    try:
        await process_job(job, file_bytes, route, store, config, meta_extractor=meta_extractor, vlm_log_store=vlm_log_store, prompts=prompts, revdoc_generator=revdoc_generator)
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
        # T5: refine rule store + refiner — shared import for both branches.
        from job_store import (
            InMemoryRefineRuleStore,
            seed_refine_rules,
        )

        if config.database_url:
            import asyncpg
            from job_store import PostgresJobStore, VLMLogStore, PromptStore, PostgresRefineRuleStore, seed_prompts
            from vlm import SEMANTIC_PROMPT
            from meta import META_PROMPT
            pool = await asyncpg.create_pool(config.database_url)
            a.state.pool = pool

            # 스키마 자동 적용 (Cortex DB 공유 환경에서도 forge_ 테이블만 생성)
            await _apply_schema(pool)

            a.state.store = PostgresJobStore(pool)
            a.state.vlm_log_store = VLMLogStore(pool)
            a.state.prompt_store = PromptStore(pool)
            await a.state.prompt_store.seed_if_empty("semantic", SEMANTIC_PROMPT)
            await a.state.prompt_store.seed_if_empty("meta_extract", META_PROMPT)
            await seed_prompts(a.state.prompt_store)

            # Load active prompts into cache
            semantic = await a.state.prompt_store.get_active("semantic")
            meta_p = await a.state.prompt_store.get_active("meta_extract")
            a.state.prompts = {
                "semantic": {"text": semantic["text"], "version": semantic["version"]} if semantic else {},
                "meta_extract": {"text": meta_p["text"], "version": meta_p["version"]} if meta_p else {},
            }

            # MetaExtractor with DB prompt
            from meta import MetaExtractor
            meta_prompt_text = a.state.prompts.get("meta_extract", {}).get("text")
            a.state.meta_extractor = MetaExtractor(config, prompt=meta_prompt_text)

            a.state.refine_rule_store = PostgresRefineRuleStore(pool)
        else:
            from job_store import InMemoryPromptStore, seed_prompts
            from vlm import SEMANTIC_PROMPT
            from meta import META_PROMPT, MetaExtractor
            a.state.prompt_store = InMemoryPromptStore()
            await a.state.prompt_store.seed_if_empty("semantic", SEMANTIC_PROMPT)
            await a.state.prompt_store.seed_if_empty("meta_extract", META_PROMPT)
            await seed_prompts(a.state.prompt_store)
            a.state.meta_extractor = MetaExtractor(config)
            a.state.refine_rule_store = InMemoryRefineRuleStore()

        await seed_refine_rules(a.state.refine_rule_store)
        a.state.refiner = await Refiner.from_store(a.state.refine_rule_store)

        # T10: reverse-doc generator — owns its own VLMClient for process_text calls.
        from vlm import VLMClient
        from revdoc.generator import ReverseDocGenerator
        a.state.revdoc_vlm = VLMClient(config)
        a.state.revdoc_generator = ReverseDocGenerator(
            vlm=a.state.revdoc_vlm,
            prompt_store=a.state.prompt_store,
            refiner=a.state.refiner,
            model=config.revdoc_model,
        )

        yield

        # shutdown
        if hasattr(a.state, "pool"):
            await a.state.pool.close()
        if hasattr(a.state, "meta_extractor"):
            await a.state.meta_extractor.close()
        if hasattr(a.state, "revdoc_vlm"):
            await a.state.revdoc_vlm.close()

    app = FastAPI(title="Forge — Document Converter", version="0.3.0", lifespan=lifespan)

    # 테스트 등 lifespan 미실행 환경을 위한 기본값
    app.state.store = store
    app.state.config = config

    from auth import verify_api_key
    from admin import create_admin_router

    auth_dep = verify_api_key(config)
    admin_router = create_admin_router(app.state, auth_dep)
    app.include_router(admin_router)

    @app.get("/health", summary="헬스체크", tags=["시스템"])
    async def health():
        """서비스 상태 확인. `{"status": "ok"}` 반환."""
        return {"status": "ok"}

    @app.post("/refine", response_model=RefineResponse, summary="MD 정제 (동기)", tags=["정제"])
    async def refine_sync(
        request: Request,
        file: UploadFile | None = File(None, description="정제할 파일 (선택)"),
        text: str | None = Form(None, description="정제할 텍스트 (선택)"),
    ):
        """동기 MD 정제. multipart form으로 file 또는 text 하나만 제공.

        6단계 정제 + validator gate를 거친 결과 + report + quality + rule_versions 반환.
        """
        if file is None and text is None:
            raise HTTPException(status_code=400, detail="file or text is required")
        if file is not None and text is not None:
            raise HTTPException(status_code=400, detail="provide file OR text, not both")

        if file is not None:
            raw = await file.read()
            if len(raw) > config.max_file_size:
                raise HTTPException(status_code=413, detail=f"File too large: max {config.max_file_size} bytes")
        else:
            raw = text  # str

        # 503 guard: exists for test-harness scenarios where create_app()
        # is invoked without running lifespan. In production Postgres mode,
        # pool creation failure would propagate and prevent app start
        # entirely; in production InMemory mode, lifespan cannot fail.
        refiner: Refiner | None = getattr(request.app.state, "refiner", None)
        if refiner is None:
            raise HTTPException(status_code=503, detail="Refiner not initialized")

        result = refiner.refine(raw)

        return RefineResponse(
            refined_text=result.text,
            report=result.report,
            quality=result.quality,
            rule_versions=result.rule_versions,
        )

    @app.post("/reverse-doc", summary="역문서 생성 (비동기)", tags=["역문서"])
    async def reverse_doc(
        request: Request,
        file: UploadFile = File(..., description="소스 코드 파일 (예: .pkb, .sql, .py)"),
        callback_url: str | None = Form(None, description="완료/실패 시 결과 POST URL"),
        requested_by: str | None = Form(None, description="요청자 식별"),
    ):
        """소스 코드 업로드 → VLM으로 역문서 MD 생성 (비동기). job_id 즉시 반환.

        REVDOC-01: 최대 200KB (일반 /convert의 100MB와 별개 제한).
        """
        raw = await file.read()

        # REVDOC-01: 200KB 제한
        if len(raw) > 200 * 1024:
            raise HTTPException(status_code=413, detail="reverse-doc max 200KB")

        source_code = raw.decode("utf-8", errors="replace")

        current_store = request.app.state.store
        job = await current_store.create(
            file.filename or "unknown",
            "reverse_doc",
            "reverse_doc",
            file_size=len(raw),
            method="reverse_doc",
            requested_by=requested_by,
        )
        job.callback_url = callback_url
        # CF-3: source_code는 Job에 dynamic 속성으로만 붙이고 DB에는 저장하지 않음.
        job.source_code = source_code

        revdoc_gen = getattr(request.app.state, "revdoc_generator", None)
        if revdoc_gen is None:
            raise HTTPException(status_code=503, detail="reverse_doc generator not initialized")

        # C4: _safe_process 래퍼 필수
        asyncio.create_task(
            _safe_process(
                job, raw, "reverse_doc", current_store, config,
                revdoc_generator=revdoc_gen,
            )
        )

        return {"job_id": job.id, "status": job.status}

    @app.post("/convert", summary="문서 변환", tags=["변환"])
    async def convert(
        file: UploadFile = File(..., description="변환할 파일 (PDF, DOCX, PPTX, XLSX, 이미지)"),
        route: str | None = Query(None, pattern="^(extract|vlm|docling)$", description="경로 강제 지정 (extract | vlm | docling)"),
        requested_by: str | None = Query(None, description="요청자 식별 (예: cortex-api)"),
        callback_url: str | None = Query(None, description="완료/실패 시 결과를 POST할 URL"),
        domain: str = Query("general", description="문서 도메인 (callback payload에 포함, Cortex 인덱싱 분류용)"),
    ):
        """파일을 업로드하면 비동기로 변환 시작. job_id 즉시 반환.

        지원 포맷: PDF, DOCX, PPTX, XLSX, JPG, PNG, TIFF, BMP.
        PPTX/이미지PDF는 VLM semantic 모드, DOCX/XLSX/텍스트PDF는 extract 모드.
        """
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
        job.callback_url = callback_url
        job.domain = domain
        meta_ext = getattr(app.state, "meta_extractor", None)
        vlm_logs = getattr(app.state, "vlm_log_store", None)
        prompts_cache = getattr(app.state, "prompts", None)
        asyncio.create_task(_safe_process(job, file_bytes, detected_route, current_store, config, meta_extractor=meta_ext, vlm_log_store=vlm_logs, prompts=prompts_cache))

        return {"job_id": job.id, "status": job.status}

    @app.get("/result/{job_id}", summary="변환 결과 조회", tags=["변환"])
    async def result(
        job_id: str,
        format: str | None = Query(None, alias="format", description="text로 지정 시 마크다운 plain text 반환"),
    ):
        """변환 결과 조회. status가 completed면 result에 마크다운 + quality + meta 포함.

        `?format=text` 추가 시 Content-Type: text/markdown으로 본문만 반환.
        """
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

    @app.post("/batch", summary="배치 변환", tags=["변환"])
    async def batch(
        files: List[UploadFile] = File(..., description="변환할 파일 목록"),
        route: str | None = Query(None, pattern="^(extract|vlm|docling)$", description="경로 강제 지정"),
        requested_by: str | None = Query(None, description="요청자 식별"),
        callback_url: str | None = Query(None, description="완료/실패 시 결과를 POST할 URL"),
        domain: str = Query("general", description="문서 도메인 (callback payload에 포함)"),
    ):
        """여러 파일 동시 변환. 각 파일별 job_id 리스트 반환. 미지원 포맷은 개별 에러."""
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
            job.callback_url = callback_url
            job.domain = domain
            meta_ext = getattr(app.state, "meta_extractor", None)
            prompts_cache = getattr(app.state, "prompts", None)
            asyncio.create_task(_safe_process(job, file_bytes, detected_route, current_store, config, meta_extractor=meta_ext, prompts=prompts_cache))
            jobs.append({"file_name": file_name, "job_id": job.id, "status": job.status})

        return {"jobs": jobs}

    return app


app = create_app()
