import asyncio
import json
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


async def _send_callback(url: str, payload: dict, headers: dict | None = None) -> None:
    """callback_url로 결과 POST. 3회 retry."""
    async with httpx.AsyncClient(timeout=30) as client:
        for attempt in range(CALLBACK_RETRIES):
            try:
                response = await client.post(url, json=payload, headers=headers)
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
    revdoc_generator=None,
    docling_log_store=None,
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

        elif route == "docling":
            # v3 (T14): docling-serve 경로. HWPX는 T15에서 office.py bridge로 처리.
            from extractors.docling_ex import extract as docling_extract
            result = await docling_extract(
                file_bytes,
                job.file_name,
                config=config,
                docling_log_store=docling_log_store,
                job_id=job.id,
            )
            await store.save_result(job.id, result)

            # docling 경로도 extract와 동일하게 메타 추출
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

        elif route == "reverse_doc":
            # T10: reverse-doc route — generator orchestrates prompt+VLM+gate+refine.
            if revdoc_generator is None:
                raise RuntimeError("reverse_doc route requires revdoc_generator")

            # source_code은 Job에 dynamic 속성(CF-3)으로 붙어 전달됨.
            # 없으면 file_bytes를 UTF-8로 디코드 (강제 재시작 후 복구 시나리오).
            source_code = getattr(job, "source_code", None)
            if source_code is None:
                source_code = file_bytes.decode("utf-8", errors="replace")

            revdoc_result = await revdoc_generator.generate(source_code, job.file_name)

            result = ConvertResult(
                text=revdoc_result.result_text,
                format="md",
                pages=1,
                file_name=job.file_name,
                source_format=job.source_format,
                route="reverse_doc",
                quality=Quality(
                    total_chars=len(revdoc_result.result_text),
                    chars_per_page=len(revdoc_result.result_text),
                    total_pages=1,
                    failed_pages=0,
                    confidence="high" if revdoc_result.gate["passed"] else "low",
                    method="reverse_doc",
                ),
            )
            await store.save_result(job.id, result)

            # gate/refine/attempts/prompt_version을 meta에 저장 (Job.meta는 dict).
            revdoc_meta = {
                "revdoc_gate": revdoc_result.gate,
                "refine_report": revdoc_result.refine_report,
                "attempts": revdoc_result.attempts,
            }
            await store.save_meta(job.id, revdoc_meta, revdoc_result.prompt_version)

    except Exception as e:
        await store.save_error(job.id, str(e))

    # Callback (callback_url은 DB가 아닌 메모리에서 전달)
    callback_url = getattr(job, 'callback_url', None)
    if callback_url:
        updated_job = await store.get(job.id)
        if updated_job:
            # Cortex /v1/ingest 호환 payload
            payload = {
                "content": updated_job.result.text if updated_job.result else "",
                "file_name": updated_job.file_name,
                "domain": getattr(job, "domain", None) or "general",
                "metadata": updated_job.meta,
                "extract": True,
                "pre_converted": True,
                # Forge 추적용 (Cortex에서 무시해도 됨)
                "forge_job_id": updated_job.id,
                "forge_status": updated_job.status,
                "forge_error": updated_job.error,
            }
            # Consumer-agnostic field rename (e.g. LightRAG content→text, file_name→file_source).
            # C6: no consumer-specific branching — generic rename only.
            if config.callback_field_map:
                # Config validator already enforces valid JSON object (string→string) at load time.
                # Defensive narrow except in case something bypasses validation — avoid
                # silently eating the callback via the blanket `except Exception` above.
                try:
                    rename_map = json.loads(config.callback_field_map)
                except json.JSONDecodeError:
                    logger.error(
                        "CALLBACK_FIELD_MAP malformed at callback time for job %s — sending unrenamed payload",
                        job.id,
                        exc_info=True,
                    )
                    rename_map = None

                if rename_map is not None:
                    renamed: dict = {}
                    for k, v in payload.items():
                        new_key = rename_map.get(k, k)
                        if new_key in renamed:
                            logger.warning(
                                "CALLBACK_FIELD_MAP: key collision on '%s' for job %s — earlier value overwritten",
                                new_key, job.id,
                            )
                        renamed[new_key] = v
                    payload = renamed
                    if not config.callback_keep_unmapped:
                        payload = {k: v for k, v in payload.items() if k in rename_map.values()}

            cb_headers = {}
            if config.callback_api_key:
                cb_headers["X-API-Key"] = config.callback_api_key
            await _send_callback(callback_url, payload, headers=cb_headers if cb_headers else None)
