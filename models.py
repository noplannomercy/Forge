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
    confidence: str  # "high" | "partial"


class ConvertResult(BaseModel):
    text: str
    format: str = "md"
    pages: int
    file_name: str
    source_format: str
    route: str  # "vlm" | "extract"
    quality: Quality


class DocumentResult(BaseModel):
    text: str
    total_pages: int
    failed_pages: int
    confidence: str  # "high" | "partial"


class Job(BaseModel):
    id: str
    status: JobStatus
    file_name: str
    source_format: str
    route: str
    result: ConvertResult | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
