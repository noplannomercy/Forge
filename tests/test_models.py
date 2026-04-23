from datetime import datetime
from models import Job, JobStatus, ConvertResult, PageResult, Quality


def test_job_creation():
    job = Job(
        id="test-uuid",
        status=JobStatus.QUEUED,
        file_name="test.pdf",
        source_format="pdf",
        route="vlm",
    )
    assert job.status == JobStatus.QUEUED
    assert job.result is None
    assert job.error is None
    assert isinstance(job.created_at, datetime)


def test_job_status_values():
    assert JobStatus.QUEUED == "queued"
    assert JobStatus.PROCESSING == "processing"
    assert JobStatus.COMPLETED == "completed"
    assert JobStatus.FAILED == "failed"


def test_page_result_success():
    pr = PageResult(page=1, text="# Title", success=True)
    assert pr.error is None


def test_page_result_failure():
    pr = PageResult(page=3, text="[변환 실패: 페이지 3]", success=False, error="timeout")
    assert pr.error == "timeout"


def test_quality():
    q = Quality(total_chars=15000, chars_per_page=333, total_pages=45, failed_pages=2, confidence="partial")
    assert q.confidence == "partial"


def test_convert_result():
    q = Quality(total_chars=500, chars_per_page=500, total_pages=1, failed_pages=0, confidence="high")
    result = ConvertResult(
        text="# Hello",
        format="md",
        pages=1,
        file_name="test.docx",
        source_format="docx",
        route="extract",
        quality=q,
    )
    assert result.route == "extract"
    assert result.quality.confidence == "high"


def test_quality_with_batch_fields():
    q = Quality(
        total_chars=2000, chars_per_page=400, total_pages=10,
        failed_pages=0, confidence="high",
        total_batches=2, failed_batches=0, method="semantic",
    )
    assert q.total_batches == 2
    assert q.failed_batches == 0
    assert q.method == "semantic"


def test_quality_extract_method():
    q = Quality(
        total_chars=500, chars_per_page=500, total_pages=1,
        failed_pages=0, confidence="high",
        total_batches=0, failed_batches=0, method="extract",
    )
    assert q.method == "extract"


def test_document_result_with_batches():
    from models import DocumentResult
    dr = DocumentResult(
        text="# Title", total_pages=10, failed_pages=0,
        confidence="high", total_batches=2, failed_batches=0,
    )
    assert dr.total_batches == 2
    assert dr.failed_batches == 0


def test_job_with_extended_fields():
    job = Job(
        id="test-uuid",
        status=JobStatus.QUEUED,
        file_name="test.pdf",
        source_format="pdf",
        route="vlm",
        method="semantic",
        requested_by="cortex-api",
        file_size=1024000,
        prompt_version="semantic-v1",
    )
    assert job.method == "semantic"
    assert job.requested_by == "cortex-api"
    assert job.file_size == 1024000
    assert job.prompt_version == "semantic-v1"
    assert job.meta == {}
    assert job.meta_prompt_version is None
    assert job.started_at is None
    assert job.processing_ms is None


def test_job_with_meta():
    job = Job(
        id="test-uuid",
        status=JobStatus.COMPLETED,
        file_name="제안서.pdf",
        source_format="pdf",
        route="vlm",
        meta={"category": "제안서", "client": "안산시"},
    )
    assert job.meta["category"] == "제안서"
    assert job.meta["client"] == "안산시"
