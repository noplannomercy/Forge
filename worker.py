from config import Config
from extractors import EXTRACTORS
from extractors.image import prepare_image
from extractors.office import pptx_to_pdf
from extractors.pdf import extract_text, pdf_to_images
from job_store import JobStore
from models import ConvertResult, DocumentResult, Job, JobStatus, Quality
from vlm import VLMClient


async def process_job(
    job: Job,
    file_bytes: bytes,
    route: str,
    store: JobStore,
    config: Config,
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

        elif route == "vlm":
            # 이미지 준비
            if job.source_format == "pptx":
                pdf_bytes = await pptx_to_pdf(file_bytes)
                images = await pdf_to_images(pdf_bytes)
            elif job.source_format == "pdf":
                images = await pdf_to_images(file_bytes)
            else:
                # jpg, png 등 이미지 파일
                img_bytes = await prepare_image(file_bytes)
                images = [img_bytes]

            # VLM semantic 호출
            vlm_client = VLMClient(config)
            try:
                doc_result: DocumentResult = await vlm_client.process_document(images)
            finally:
                await vlm_client.close()

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

    except Exception as e:
        await store.save_error(job.id, str(e))
