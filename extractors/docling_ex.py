"""Docling extractor — calls docling-serve over HTTP (Option B).

Does NOT import the docling library. Uses httpx to POST multipart to
``DOCLING_SERVE_URL/v1/convert/file`` and falls back to pypdfium2 on any
failure (HTTP non-200, empty md_content, network error, timeout, …).

Design:
- S4-compliant: ``async def extract(file_bytes, file_name) -> ConvertResult``.
  Extra kwargs (``config``, ``docling_log_store``, ``job_id``) are optional
  observability hooks; basic S4 callers still work with just 2 args.
- Shared Semaphore with VLM (plan Q1 decision) — sized by ``vlm_concurrency``.
- Fallback delegates to ``extractors.pdf.extract_text`` and stamps
  ``quality.method='pypdfium2_fallback'`` while keeping ``route='docling'``
  (what was requested).
- C1/C6-compliant: no Cortex / LightRAG / docling library imports.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time

import httpx

from models import ConvertResult, Quality

logger = logging.getLogger(__name__)

# Shared semaphore — sized to VLM_CONCURRENCY (plan Q1: shared, not separate pool)
_DOCLING_SEMAPHORE: asyncio.Semaphore | None = None


def _get_semaphore(concurrency: int) -> asyncio.Semaphore:
    """Lazy-init a module-level semaphore reused across calls in the same loop."""
    global _DOCLING_SEMAPHORE
    if _DOCLING_SEMAPHORE is None:
        _DOCLING_SEMAPHORE = asyncio.Semaphore(concurrency)
    return _DOCLING_SEMAPHORE


def _estimate_pages_from_md(md: str) -> int:
    """Very rough page-count estimate.

    docling-serve's public contract (``document.md_content``) does not
    expose page count directly, so we approximate using ~3000 chars/page.
    This is only used to populate ``pages`` / quality metrics; router/
    worker do not rely on exactness.
    """
    return max(1, len(md) // 3000)


def _guess_source_format(file_name: str) -> str:
    ext = os.path.splitext(file_name)[1].lower().lstrip(".")
    return ext or "unknown"


async def extract(
    file_bytes: bytes,
    file_name: str,
    *,
    config=None,
    docling_log_store=None,
    job_id=None,
) -> ConvertResult:
    """Convert a PDF via docling-serve (HTTP).

    Args:
        file_bytes: raw PDF bytes.
        file_name: original filename (e.g. ``report.pdf``).
        config: optional ``Config`` override. Defaults to the global ``config``.
        docling_log_store: optional T13 ``DoclingLogStore`` — if present and
            ``job_id`` is supplied, we emit one log row per call.
        job_id: optional job id used for log correlation.

    Returns:
        ``ConvertResult`` with ``route='docling'``. On any failure we still
        return a ``ConvertResult`` (sourced from pypdfium2 fallback) — callers
        never see an exception for a transient docling-serve issue.
    """
    # Lazy import to avoid circular-import risk. No module-level singleton
    # exists in config.py, so we instantiate Config() on demand.
    if config is None:
        from config import Config
        cfg = Config()
    else:
        cfg = config

    if not cfg.docling_serve_url:
        # No URL configured → immediate fallback (keeps local dev working).
        return await _fallback(
            file_bytes, file_name,
            reason="DOCLING_SERVE_URL not configured",
            status_code=None,
            docling_log_store=docling_log_store, job_id=job_id,
        )

    semaphore = _get_semaphore(cfg.vlm_concurrency)
    t0 = time.time()

    try:
        async with semaphore:
            async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:
                headers: dict[str, str] = {}
                if cfg.docling_api_key:
                    headers["X-Api-Key"] = cfg.docling_api_key

                files = {"files": (file_name, file_bytes, "application/octet-stream")}
                # docling-serve accepts repeated multipart fields for list values;
                # single string values are fine here.
                data = {
                    "to_formats": "md",
                    # "placeholder" keeps the MD lean (DOCLING-06: images as <!-- image -->);
                    # "embedded" base64-inlines and can bloat MD 10-100x.
                    "image_export_mode": "placeholder",
                }
                url = cfg.docling_serve_url.rstrip("/") + "/v1/convert/file"
                resp = await client.post(url, files=files, data=data, headers=headers)
                latency_ms = int((time.time() - t0) * 1000)

                if resp.status_code != 200:
                    reason = f"docling-serve HTTP {resp.status_code}"
                    return await _fallback(
                        file_bytes, file_name, reason=reason,
                        status_code=resp.status_code,
                        docling_log_store=docling_log_store, job_id=job_id,
                    )

                try:
                    payload = resp.json()
                except ValueError as e:
                    reason = f"docling-serve returned non-JSON: {e}"
                    return await _fallback(
                        file_bytes, file_name, reason=reason,
                        status_code=resp.status_code,
                        docling_log_store=docling_log_store, job_id=job_id,
                    )

                document = payload.get("document") or {}
                md = document.get("md_content") or ""
                if not md:
                    reason = "docling-serve returned empty md_content"
                    return await _fallback(
                        file_bytes, file_name, reason=reason,
                        status_code=resp.status_code,
                        docling_log_store=docling_log_store, job_id=job_id,
                    )

                pages = _estimate_pages_from_md(md)

                if docling_log_store is not None and job_id is not None:
                    await docling_log_store.insert(
                        job_id=job_id,
                        pages=pages,
                        latency_ms=latency_ms,
                        status_code=resp.status_code,
                        fallback=False,
                        reason=None,
                    )

                return ConvertResult(
                    text=md,
                    format="md",
                    pages=pages,
                    file_name=file_name,
                    source_format=_guess_source_format(file_name),
                    route="docling",
                    quality=Quality(
                        total_chars=len(md),
                        chars_per_page=len(md) / max(pages, 1),
                        total_pages=pages,
                        failed_pages=0,
                        confidence="high",
                        method="docling",
                    ),
                )
    except (httpx.HTTPError, asyncio.TimeoutError, OSError) as e:
        reason = f"{type(e).__name__}: {e}"
        logger.warning("docling-serve call failed: %s — falling back to pypdfium2", reason)
        return await _fallback(
            file_bytes, file_name, reason=reason, status_code=0,
            docling_log_store=docling_log_store, job_id=job_id,
        )


async def _fallback(
    file_bytes: bytes,
    file_name: str,
    *,
    reason: str,
    status_code: int | None,
    docling_log_store,
    job_id,
) -> ConvertResult:
    """Delegate to pypdfium2 and tag the result as a docling fallback.

    ``route`` stays ``"docling"`` (the caller asked for docling) while
    ``quality.method`` becomes ``"pypdfium2_fallback"`` so downstream can
    distinguish a real docling pass from a rescue.
    """
    from extractors.pdf import extract_text as pdf_extract
    result = await pdf_extract(file_bytes, file_name)
    result.quality.method = "pypdfium2_fallback"
    result.route = "docling"
    if docling_log_store is not None and job_id is not None:
        await docling_log_store.insert(
            job_id=job_id,
            pages=result.pages,
            latency_ms=0,
            status_code=status_code,
            fallback=True,
            reason=reason,
        )
    return result
