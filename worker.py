import asyncio
import logging

import httpx

from config import Config
from extractors import EXTRACTORS
from extractors.image import prepare_image
from extractors.office import pptx_to_pdf
from extractors.pdf import extract_text, pdf_to_images
from job_store import JobStore
from meta import MetaExtractor
from models import ConvertResult, DocumentResult, Job, JobStatus, Quality
from vlm import VLMClient

logger = logging.getLogger(__name__)

CALLBACK_RETRIES = 3
CALLBACK_DELAYS = [1, 2, 4]


async def _send_callback(url: str, payload: dict) -> None:
    """callback_url로 결과 POST. 3회 retry."""
    async with httpx.AsyncClient(timeout=30) as client:
        for attempt in range(CALLBACK_RETRIES):
            try:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                logger.info("Callback sent to %s (status %d)", url, response.status_code)
                return
            except Exception as e:
                logger.warning("Callback attempt %d failed: %s", attempt + 1, e)
                if attempt < CALLBACK_RETRIES - 1:
                    await asyncio.sleep(CALLBACK_DELAYS[attempt])
    logger.error("Callback failed after %d attempts: %s", CALLBACK_RETRIES, url)


async def _extract_meta(result_text: str, meta_extractor: MetaExtractor | None, config: Config, prompts: dict | None = None) -> dict:
    """메타 추출. 실패 시 빈 dict 반환. meta_extractor가 없으면 임시 생성."""
    extractor = meta_extractor
    should_close = False
    if extractor is None:
        meta_prompt_info = prompts.get("meta_extract", {}) if prompts else {}
        meta_text = meta_prompt_info.get("text")
        extractor = MetaExtractor(config, prompt=meta_text)
        should_close = True
    try:
        return await extractor.extract(result_text)
    except Exception:
        logger.warning("Meta extraction failed for job", exc_info=True)
        return {}
    finally:
        if should_close:
            await extractor.close()


async def process_job(
    job: Job,
    file_bytes: bytes,
    route: str,
    store: JobStore,
    config: Config,
    meta_extractor: MetaExtractor | None = None,
    vlm_log_store=None,
    prompts: dict | None = None,
) -> None:
    """비동기 변환 워커. asyncio.create_task로 호출됨."""
    await store.update_status(job.id, JobStatus.PROCESSING)

    try:
        if route == "extract":
            if job.source_format == "pdf":
                result = await extract_text(file_bytes, job.file_name)
            else:
                result = await EXTRACTORS[job.source_format](file_bytes, job.file_name)
            await store.save_result(job.id, result)

            # extract 경로도 메타 추출
            meta_prompt_info = prompts.get("meta_extract", {}) if prompts else {}
            meta_ver = f"meta_extract-v{meta_prompt_info.get('version', '?')}" if meta_prompt_info else "meta_extract-v?"
            meta = await _extract_meta(result.text, meta_extractor, config, prompts=prompts)
            if meta:
                await store.save_meta(job.id, meta, meta_ver)

        elif route == "vlm":
            # 이미지 준비
            if job.source_format == "pptx":
                pdf_bytes = await pptx_to_pdf(file_bytes)
                images = await pdf_to_images(pdf_bytes)
            elif job.source_format == "pdf":
                images = await pdf_to_images(file_bytes)
            else:
                img_bytes = await prepare_image(file_bytes)
                images = [img_bytes]

            # VLM semantic 호출
            semantic_prompt = prompts.get("semantic", {}) if prompts else {}
            prompt_text = semantic_prompt.get("text")
            prompt_ver = f"semantic-v{semantic_prompt.get('version', '?')}" if semantic_prompt else "semantic-v?"
            vlm_client = VLMClient(config, prompt=prompt_text)
            try:
                doc_result, batch_results = await vlm_client.process_document(images)
            finally:
                await vlm_client.close()

            # VLM 로그 기록
            if vlm_log_store:
                for br in batch_results:
                    try:
                        await vlm_log_store.log(
                            job_id=job.id, batch_num=br.batch_num, purpose="convert",
                            model=config.vlm_model, prompt_version=prompt_ver,
                            input_tokens=br.input_tokens, output_tokens=br.output_tokens,
                            cost_usd=None, latency_ms=br.latency_ms,
                            success=br.success, error=br.error,
                        )
                    except Exception:
                        logger.warning("Failed to log VLM batch %d", br.batch_num, exc_info=True)

            result = ConvertResult(
                text=doc_result.text,
                format="md",
                pages=doc_result.total_pages,
                file_name=job.file_name,
                source_format=job.source_format,
                route="vlm",
                quality=Quality(
                    total_chars=len(doc_result.text),
                    chars_per_page=len(doc_result.text) / doc_result.total_pages if doc_result.total_pages > 0 else 0,
                    total_pages=doc_result.total_pages,
                    failed_pages=doc_result.failed_pages,
                    confidence=doc_result.confidence,
                    total_batches=doc_result.total_batches,
                    failed_batches=doc_result.failed_batches,
                    method="semantic",
                ),
            )
            await store.save_result(job.id, result)

            # 메타 추출
            meta_prompt_info = prompts.get("meta_extract", {}) if prompts else {}
            meta_ver = f"meta_extract-v{meta_prompt_info.get('version', '?')}" if meta_prompt_info else "meta_extract-v?"
            meta = await _extract_meta(result.text, meta_extractor, config, prompts=prompts)
            if meta:
                await store.save_meta(job.id, meta, meta_ver)

    except Exception as e:
        await store.save_error(job.id, str(e))

    # Callback
    if job.callback_url:
        updated_job = await store.get(job.id)
        if updated_job:
            # Cortex /v1/ingest 호환 payload
            payload = {
                "content": updated_job.result.text if updated_job.result else "",
                "file_name": updated_job.file_name,
                "domain": "general",
                "metadata": updated_job.meta,
                "extract": True,
                # Forge 추적용 (Cortex에서 무시해도 됨)
                "forge_job_id": updated_job.id,
                "forge_status": updated_job.status,
                "forge_error": updated_job.error,
            }
            await _send_callback(job.callback_url, payload)
