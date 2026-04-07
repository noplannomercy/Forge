from datetime import datetime, timezone
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
