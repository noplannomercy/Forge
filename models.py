from datetime import datetime, timezone
from enum import StrEnum
from pydantic import BaseModel, Field


class JobStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class PageResult(BaseModel):
    page: int
    text: str
    success: bool
    error: str | None = None


class Quality(BaseModel):
    total_chars: int
    chars_per_page: float
    total_pages: int
    failed_pages: int
    confidence: str  # "high" | "partial" | "low"
    total_batches: int = 0
    failed_batches: int = 0
    method: str = "extract"


class ConvertResult(BaseModel):
    text: str
    format: str = "md"
    pages: int
    file_name: str
    source_format: str
    route: str  # "vlm" | "extract" | "docling" | "reverse_doc" | "refine"
    quality: Quality


class DocumentResult(BaseModel):
    text: str
    total_pages: int
    failed_pages: int
    confidence: str  # "high" | "partial" | "low"
    total_batches: int = 0
    failed_batches: int = 0


class RefineResponse(BaseModel):
    refined_text: str
    report: dict  # per-stage StageReport dicts
    quality: dict  # {"gate": "pass"|"fail", "checks": {...}, "reason"?: str}
    rule_versions: dict  # {stage_name: version}


class Job(BaseModel):
    id: str
    status: JobStatus
    file_name: str
    file_size: int | None = None
    source_format: str
    route: str
    method: str = "extract"
    requested_by: str | None = None
    result: ConvertResult | None = None
    meta: dict = Field(default_factory=dict)
    prompt_version: str | None = None
    meta_prompt_version: str | None = None
    callback_url: str | None = None
    domain: str = "general"
    # T10 (CF-3): reverse_doc source code held in memory only — never persisted to DB.
    source_code: str | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: datetime | None = None
    completed_at: datetime | None = None
    processing_ms: int | None = None
