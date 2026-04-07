# Forge Document Converter Service v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 다양한 포맷(PDF, DOCX, PPTX, XLSX, 이미지)을 Markdown으로 변환하는 비동기 REST 마이크로서비스 구축

**Architecture:** 단일 프로세스 FastAPI 서비스. 파일 업로드 → 포맷 감지 → 추출(텍스트 기반) 또는 VLM(이미지 기반) 경로 분기 → 비동기 Job으로 처리. JobStore 인터페이스 분리로 Redis 전환 대비.

**Tech Stack:** Python 3.11, FastAPI, uvicorn, httpx, pydantic-settings, pypdfium2, Pillow, python-docx, python-pptx, openpyxl, pytest, pytest-asyncio

---

## File Map

| 파일 | 역할 | Task |
|------|------|------|
| `requirements.txt` | 의존성 | 1 |
| `.env.example` | 환경변수 템플릿 | 1 |
| `config.py` | 환경변수 로드 (pydantic-settings) | 1 |
| `models.py` | Pydantic 모델 (Job, ConvertResult, PageResult, Quality) | 2 |
| `job_store.py` | JobStore ABC + InMemoryJobStore | 3 |
| `router.py` | 포맷 감지 + 경로 결정 | 4 |
| `extractors/__init__.py` | extractor 레지스트리 | 5 |
| `extractors/docx.py` | DOCX → md | 5 |
| `extractors/pptx.py` | PPTX → md | 6 |
| `extractors/xlsx.py` | XLSX → md | 7 |
| `extractors/pdf.py` | PDF 텍스트 추출 + 이미지 변환 | 8 |
| `extractors/image.py` | 이미지 전처리 | 8 |
| `vlm.py` | VLM 클라이언트 (httpx async) | 9 |
| `worker.py` | 비동기 변환 워커 | 10 |
| `app.py` | FastAPI 엔드포인트 | 11 |
| `Dockerfile` | Docker 빌드 | 12 |
| `tests/` | 전체 테스트 | 1-11 |

---

### Task 1: 프로젝트 셋업 + Config

**Files:**
- Create: `requirements.txt`
- Create: `.env.example`
- Create: `config.py`
- Create: `tests/__init__.py`
- Create: `tests/test_config.py`

**SRS 커버:** CONFIG-01, CONFIG-02, CONFIG-03, CONFIG-04

- [ ] **Step 1: requirements.txt 작성**

```
# 코어
fastapi>=0.115.0
uvicorn>=0.30.0
httpx>=0.27.0
pydantic-settings>=2.0.0

# VLM 경로
pypdfium2>=4.0.0
Pillow>=10.0.0

# 추출 경로
python-docx>=1.1.0
python-pptx>=1.0.0
openpyxl>=3.1.0

# 테스트
pytest>=8.0.0
pytest-asyncio>=0.24.0
```

- [ ] **Step 2: .env.example 작성**

```
VLM_URL=http://localhost:11434/v1/chat/completions
VLM_MODEL=qwen2-vl:7b
VLM_API_KEY=
VLM_TIMEOUT=120
VLM_CONCURRENCY=3
HOST=0.0.0.0
PORT=8003
```

- [ ] **Step 3: 테스트 작성 — config.py**

```python
# tests/test_config.py
import os
import pytest
from config import Config


def test_config_defaults():
    config = Config()
    assert config.vlm_url == "http://localhost:11434/v1/chat/completions"
    assert config.vlm_model == "qwen2-vl:7b"
    assert config.vlm_api_key == ""
    assert config.vlm_timeout == 120
    assert config.vlm_concurrency == 3
    assert config.host == "0.0.0.0"
    assert config.port == 8003


def test_config_from_env(monkeypatch):
    monkeypatch.setenv("VLM_URL", "http://custom:8080/v1/chat/completions")
    monkeypatch.setenv("VLM_MODEL", "gpt-4o")
    monkeypatch.setenv("VLM_TIMEOUT", "60")
    monkeypatch.setenv("VLM_CONCURRENCY", "5")
    config = Config()
    assert config.vlm_url == "http://custom:8080/v1/chat/completions"
    assert config.vlm_model == "gpt-4o"
    assert config.vlm_timeout == 60
    assert config.vlm_concurrency == 5
```

- [ ] **Step 4: 테스트 실패 확인**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'config'`

- [ ] **Step 5: config.py 구현**

```python
# config.py
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    vlm_url: str = "http://localhost:11434/v1/chat/completions"
    vlm_model: str = "qwen2-vl:7b"
    vlm_api_key: str = ""
    vlm_timeout: int = 120
    vlm_concurrency: int = 3
    host: str = "0.0.0.0"
    port: int = 8003

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")
```

- [ ] **Step 6: 테스트 통과 확인**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/test_config.py -v`
Expected: 2 passed

- [ ] **Step 7: 가상환경 생성 + 의존성 설치 (아직 안 되어있으면)**

```bash
cd C:/workspace/prj20060203/Forge
python -m venv .venv
source .venv/Scripts/activate  # Windows git bash
pip install -r requirements.txt
```

- [ ] **Step 8: 커밋**

```bash
git add requirements.txt .env.example config.py tests/__init__.py tests/test_config.py
git commit -m "feat: project setup — requirements, config, env template"
```

---

### Task 2: Pydantic Models

**Files:**
- Create: `models.py`
- Create: `tests/test_models.py`

**SRS 커버:** API-03, API-06 (응답 모델 정의)

- [ ] **Step 1: 테스트 작성 — models.py**

```python
# tests/test_models.py
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
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'models'`

- [ ] **Step 3: models.py 구현**

```python
# models.py
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
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/test_models.py -v`
Expected: 6 passed

- [ ] **Step 5: 커밋**

```bash
git add models.py tests/test_models.py
git commit -m "feat: pydantic models — Job, ConvertResult, PageResult, Quality"
```

---

### Task 3: JobStore

**Files:**
- Create: `job_store.py`
- Create: `tests/test_job_store.py`

**SRS 커버:** 데이터 모델, 상태 정의

- [ ] **Step 1: 테스트 작성 — job_store.py**

```python
# tests/test_job_store.py
import pytest
from job_store import InMemoryJobStore
from models import JobStatus, ConvertResult, Quality


@pytest.fixture
def store():
    return InMemoryJobStore()


@pytest.mark.asyncio
async def test_create_job(store):
    job = await store.create("test.pdf", "pdf", "vlm")
    assert job.status == JobStatus.QUEUED
    assert job.file_name == "test.pdf"
    assert job.source_format == "pdf"
    assert job.route == "vlm"
    assert job.id  # uuid가 할당됨


@pytest.mark.asyncio
async def test_get_job(store):
    job = await store.create("test.pdf", "pdf", "vlm")
    fetched = await store.get(job.id)
    assert fetched is not None
    assert fetched.id == job.id


@pytest.mark.asyncio
async def test_get_nonexistent_returns_none(store):
    result = await store.get("nonexistent-id")
    assert result is None


@pytest.mark.asyncio
async def test_update_status(store):
    job = await store.create("test.pdf", "pdf", "vlm")
    await store.update_status(job.id, JobStatus.PROCESSING)
    fetched = await store.get(job.id)
    assert fetched.status == JobStatus.PROCESSING


@pytest.mark.asyncio
async def test_save_result(store):
    job = await store.create("test.docx", "docx", "extract")
    quality = Quality(total_chars=100, chars_per_page=100, total_pages=1, failed_pages=0, confidence="high")
    result = ConvertResult(
        text="# Hello", format="md", pages=1,
        file_name="test.docx", source_format="docx",
        route="extract", quality=quality,
    )
    await store.save_result(job.id, result)
    fetched = await store.get(job.id)
    assert fetched.status == JobStatus.COMPLETED
    assert fetched.result.text == "# Hello"
    assert fetched.completed_at is not None


@pytest.mark.asyncio
async def test_save_error(store):
    job = await store.create("bad.xyz", "xyz", "extract")
    await store.save_error(job.id, "UnsupportedFormat: .xyz")
    fetched = await store.get(job.id)
    assert fetched.status == JobStatus.FAILED
    assert fetched.error == "UnsupportedFormat: .xyz"
    assert fetched.completed_at is not None
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/test_job_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'job_store'`

- [ ] **Step 3: job_store.py 구현**

```python
# job_store.py
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone

from models import ConvertResult, Job, JobStatus


class JobStore(ABC):
    @abstractmethod
    async def create(self, file_name: str, source_format: str, route: str) -> Job: ...

    @abstractmethod
    async def get(self, job_id: str) -> Job | None: ...

    @abstractmethod
    async def update_status(self, job_id: str, status: JobStatus) -> None: ...

    @abstractmethod
    async def save_result(self, job_id: str, result: ConvertResult) -> None: ...

    @abstractmethod
    async def save_error(self, job_id: str, error: str) -> None: ...


class InMemoryJobStore(JobStore):
    def __init__(self):
        self._jobs: dict[str, Job] = {}

    async def create(self, file_name: str, source_format: str, route: str) -> Job:
        job = Job(
            id=str(uuid.uuid4()),
            status=JobStatus.QUEUED,
            file_name=file_name,
            source_format=source_format,
            route=route,
        )
        self._jobs[job.id] = job
        return job

    async def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    async def update_status(self, job_id: str, status: JobStatus) -> None:
        if job_id in self._jobs:
            self._jobs[job_id].status = status

    async def save_result(self, job_id: str, result: ConvertResult) -> None:
        if job_id in self._jobs:
            job = self._jobs[job_id]
            job.status = JobStatus.COMPLETED
            job.result = result
            job.completed_at = datetime.now(timezone.utc)

    async def save_error(self, job_id: str, error: str) -> None:
        if job_id in self._jobs:
            job = self._jobs[job_id]
            job.status = JobStatus.FAILED
            job.error = error
            job.completed_at = datetime.now(timezone.utc)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/test_job_store.py -v`
Expected: 6 passed

- [ ] **Step 5: 커밋**

```bash
git add job_store.py tests/test_job_store.py
git commit -m "feat: JobStore ABC + InMemoryJobStore with full CRUD"
```

---

### Task 4: Router (포맷 감지 + 경로 결정)

**Files:**
- Create: `router.py`
- Create: `tests/test_router.py`

**SRS 커버:** ROUTE-01, ROUTE-02, ROUTE-03, ROUTE-04, ROUTE-05

- [ ] **Step 1: 테스트 작성 — router.py**

```python
# tests/test_router.py
import pytest
from router import detect_route, UnsupportedFormatError


def test_docx_routes_to_extract():
    route, fmt = detect_route("report.docx", b"dummy")
    assert route == "extract"
    assert fmt == "docx"


def test_pptx_routes_to_extract():
    route, fmt = detect_route("slides.pptx", b"dummy")
    assert route == "extract"
    assert fmt == "pptx"


def test_xlsx_routes_to_extract():
    route, fmt = detect_route("data.xlsx", b"dummy")
    assert route == "extract"
    assert fmt == "xlsx"


def test_jpg_routes_to_vlm():
    route, fmt = detect_route("photo.jpg", b"dummy")
    assert route == "vlm"
    assert fmt == "jpg"


def test_jpeg_routes_to_vlm():
    route, fmt = detect_route("photo.jpeg", b"dummy")
    assert route == "vlm"
    assert fmt == "jpeg"


def test_png_routes_to_vlm():
    route, fmt = detect_route("screenshot.png", b"dummy")
    assert route == "vlm"
    assert fmt == "png"


def test_tiff_routes_to_vlm():
    route, fmt = detect_route("scan.tiff", b"dummy")
    assert route == "vlm"
    assert fmt == "tiff"


def test_bmp_routes_to_vlm():
    route, fmt = detect_route("image.bmp", b"dummy")
    assert route == "vlm"
    assert fmt == "bmp"


def test_unsupported_format_raises():
    with pytest.raises(UnsupportedFormatError) as exc_info:
        detect_route("file.xyz", b"dummy")
    assert ".xyz" in str(exc_info.value)


def test_case_insensitive():
    route, fmt = detect_route("REPORT.DOCX", b"dummy")
    assert route == "extract"
    assert fmt == "docx"


def test_pdf_with_text_routes_to_extract(tmp_path):
    """텍스트가 충분한 PDF → extract 경로"""
    # 실제 PDF 없이 try_extract_pdf_text를 모킹
    from unittest.mock import patch
    with patch("router.try_extract_pdf_text", return_value=5000):
        route, fmt = detect_route("report.pdf", b"fakepdf")
    assert route == "extract"
    assert fmt == "pdf"


def test_pdf_scan_routes_to_vlm():
    """텍스트가 거의 없는 PDF → vlm 경로"""
    from unittest.mock import patch
    with patch("router.try_extract_pdf_text", return_value=50):
        route, fmt = detect_route("scan.pdf", b"fakepdf")
    assert route == "vlm"
    assert fmt == "pdf"
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/test_router.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'router'`

- [ ] **Step 3: router.py 구현**

```python
# router.py
from pathlib import Path

import pypdfium2 as pdfium


class UnsupportedFormatError(Exception):
    pass


EXTRACT_FORMATS = {".docx", ".pptx", ".xlsx"}
VLM_FORMATS = {".jpg", ".jpeg", ".png", ".tiff", ".bmp"}


def try_extract_pdf_text(file_bytes: bytes) -> float:
    """PDF에서 텍스트 추출 시도. chars_per_mb 반환."""
    try:
        pdf = pdfium.PdfDocument(file_bytes)
        total_text = ""
        for page_index in range(len(pdf)):
            page = pdf[page_index]
            textpage = page.get_textpage()
            total_text += textpage.get_text_range()
            textpage.close()
            page.close()
        pdf.close()
        size_mb = len(file_bytes) / 1_000_000
        if size_mb == 0:
            return 0
        return len(total_text) / size_mb
    except Exception:
        return 0


def detect_route(file_name: str, file_bytes: bytes) -> tuple[str, str]:
    """파일명과 바이트로 처리 경로 결정. (route, source_format) 반환."""
    ext = Path(file_name).suffix.lower()

    if ext in EXTRACT_FORMATS:
        return ("extract", ext[1:])

    if ext in VLM_FORMATS:
        return ("vlm", ext[1:])

    if ext == ".pdf":
        chars_per_mb = try_extract_pdf_text(file_bytes)
        if chars_per_mb < 100:
            return ("vlm", "pdf")
        return ("extract", "pdf")

    raise UnsupportedFormatError(f"Unsupported format: {ext}")
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/test_router.py -v`
Expected: 12 passed

- [ ] **Step 5: 커밋**

```bash
git add router.py tests/test_router.py
git commit -m "feat: format detection router — extract vs vlm routing"
```

---

### Task 5: DOCX Extractor

**Files:**
- Create: `extractors/__init__.py`
- Create: `extractors/docx.py`
- Create: `tests/test_extractor_docx.py`
- Create: `tests/fixtures/` (테스트 픽스처 디렉토리)

**SRS 커버:** EXTRACT-01

- [ ] **Step 1: 테스트 픽스처 — 간단한 DOCX 생성 헬퍼**

```python
# tests/conftest.py
import io
import pytest
from docx import Document as DocxDocument
from openpyxl import Workbook
from pptx import Presentation


@pytest.fixture
def sample_docx_bytes():
    """텍스트 + 표가 있는 간단한 DOCX"""
    doc = DocxDocument()
    doc.add_heading("제목", level=1)
    doc.add_paragraph("본문 텍스트입니다.")
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "이름"
    table.cell(0, 1).text = "나이"
    table.cell(1, 0).text = "홍길동"
    table.cell(1, 1).text = "30"
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


@pytest.fixture
def empty_docx_bytes():
    """빈 DOCX"""
    doc = DocxDocument()
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


@pytest.fixture
def sample_pptx_bytes():
    """슬라이드 2개짜리 PPTX"""
    prs = Presentation()
    slide1 = prs.slides.add_slide(prs.slide_layouts[0])
    slide1.shapes.title.text = "슬라이드 1 제목"
    slide1.placeholders[1].text = "슬라이드 1 본문"
    slide2 = prs.slides.add_slide(prs.slide_layouts[1])
    slide2.shapes.title.text = "슬라이드 2 제목"
    slide2.placeholders[1].text = "슬라이드 2 본문"
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


@pytest.fixture
def sample_xlsx_bytes():
    """시트 2개짜리 XLSX"""
    wb = Workbook()
    ws1 = wb.active
    ws1.title = "매출"
    ws1.append(["월", "금액"])
    ws1.append(["1월", 1000])
    ws1.append(["2월", 2000])
    ws2 = wb.create_sheet("비용")
    ws2.append(["항목", "금액"])
    ws2.append(["인건비", 500])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
```

- [ ] **Step 2: 테스트 작성 — docx extractor**

```python
# tests/test_extractor_docx.py
import pytest
from extractors.docx import extract


@pytest.mark.asyncio
async def test_docx_extracts_heading(sample_docx_bytes):
    result = await extract(sample_docx_bytes, "test.docx")
    assert "# 제목" in result.text


@pytest.mark.asyncio
async def test_docx_extracts_paragraph(sample_docx_bytes):
    result = await extract(sample_docx_bytes, "test.docx")
    assert "본문 텍스트입니다" in result.text


@pytest.mark.asyncio
async def test_docx_extracts_table(sample_docx_bytes):
    result = await extract(sample_docx_bytes, "test.docx")
    assert "이름" in result.text
    assert "홍길동" in result.text
    assert "|" in result.text  # markdown 표 형식


@pytest.mark.asyncio
async def test_docx_result_metadata(sample_docx_bytes):
    result = await extract(sample_docx_bytes, "test.docx")
    assert result.source_format == "docx"
    assert result.route == "extract"
    assert result.format == "md"
    assert result.quality.confidence == "high"
    assert result.quality.total_chars > 0


@pytest.mark.asyncio
async def test_empty_docx(empty_docx_bytes):
    result = await extract(empty_docx_bytes, "empty.docx")
    assert result.text == "" or result.text.strip() == ""
    assert result.quality.total_chars == 0
```

- [ ] **Step 3: 테스트 실패 확인**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/test_extractor_docx.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'extractors'`

- [ ] **Step 4: extractors/__init__.py + docx.py 구현**

```python
# extractors/__init__.py
from extractors.docx import extract as extract_docx
from extractors.pptx import extract as extract_pptx
from extractors.xlsx import extract as extract_xlsx

EXTRACTORS: dict[str, callable] = {
    "docx": extract_docx,
    "pptx": extract_pptx,
    "xlsx": extract_xlsx,
}
```

> 주의: pptx, xlsx는 아직 미구현이므로 __init__.py는 Task 7 완료 후 최종 등록. 우선 docx만 import하고 나머지는 주석 처리.

임시 __init__.py:

```python
# extractors/__init__.py
from extractors.docx import extract as extract_docx

EXTRACTORS: dict[str, callable] = {
    "docx": extract_docx,
}
```

```python
# extractors/docx.py
import io
from docx import Document

from models import ConvertResult, Quality


def _table_to_md(table) -> str:
    """docx 표 → markdown 표 변환"""
    rows = []
    for row in table.rows:
        cells = [cell.text.strip() for cell in row.cells]
        rows.append("| " + " | ".join(cells) + " |")
    if len(rows) >= 1:
        header_sep = "| " + " | ".join(["---"] * len(table.rows[0].cells)) + " |"
        rows.insert(1, header_sep)
    return "\n".join(rows)


async def extract(file_bytes: bytes, file_name: str) -> ConvertResult:
    """DOCX → Markdown 변환"""
    doc = Document(io.BytesIO(file_bytes))
    parts: list[str] = []

    for element in doc.element.body:
        tag = element.tag.split("}")[-1]  # namespace 제거

        if tag == "p":
            # paragraph
            para = None
            for p in doc.paragraphs:
                if p._element is element:
                    para = p
                    break
            if para is None:
                continue
            text = para.text.strip()
            if not text:
                continue
            style_name = para.style.name if para.style else ""
            if "Heading 1" in style_name:
                parts.append(f"# {text}")
            elif "Heading 2" in style_name:
                parts.append(f"## {text}")
            elif "Heading 3" in style_name:
                parts.append(f"### {text}")
            else:
                parts.append(text)

        elif tag == "tbl":
            for table in doc.tables:
                if table._element is element:
                    parts.append(_table_to_md(table))
                    break

    full_text = "\n\n".join(parts)
    total_chars = len(full_text.strip())

    return ConvertResult(
        text=full_text,
        format="md",
        pages=1,
        file_name=file_name,
        source_format="docx",
        route="extract",
        quality=Quality(
            total_chars=total_chars,
            chars_per_page=total_chars if total_chars > 0 else 0,
            total_pages=1,
            failed_pages=0,
            confidence="high",
        ),
    )
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/test_extractor_docx.py -v`
Expected: 5 passed

- [ ] **Step 6: 커밋**

```bash
git add extractors/__init__.py extractors/docx.py tests/conftest.py tests/test_extractor_docx.py
git commit -m "feat: DOCX extractor — text + table to markdown"
```

---

### Task 6: PPTX Extractor

**Files:**
- Create: `extractors/pptx.py`
- Create: `tests/test_extractor_pptx.py`

**SRS 커버:** EXTRACT-02

- [ ] **Step 1: 테스트 작성 — pptx extractor**

```python
# tests/test_extractor_pptx.py
import pytest
from extractors.pptx import extract


@pytest.mark.asyncio
async def test_pptx_extracts_slide_titles(sample_pptx_bytes):
    result = await extract(sample_pptx_bytes, "test.pptx")
    assert "슬라이드 1 제목" in result.text
    assert "슬라이드 2 제목" in result.text


@pytest.mark.asyncio
async def test_pptx_extracts_slide_body(sample_pptx_bytes):
    result = await extract(sample_pptx_bytes, "test.pptx")
    assert "슬라이드 1 본문" in result.text
    assert "슬라이드 2 본문" in result.text


@pytest.mark.asyncio
async def test_pptx_slide_numbering(sample_pptx_bytes):
    result = await extract(sample_pptx_bytes, "test.pptx")
    assert "## 슬라이드 1" in result.text
    assert "## 슬라이드 2" in result.text


@pytest.mark.asyncio
async def test_pptx_result_metadata(sample_pptx_bytes):
    result = await extract(sample_pptx_bytes, "test.pptx")
    assert result.source_format == "pptx"
    assert result.route == "extract"
    assert result.pages == 2
    assert result.quality.total_pages == 2
    assert result.quality.confidence == "high"
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/test_extractor_pptx.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'extractors.pptx'`

- [ ] **Step 3: extractors/pptx.py 구현**

```python
# extractors/pptx.py
import io
from pptx import Presentation

from models import ConvertResult, Quality


async def extract(file_bytes: bytes, file_name: str) -> ConvertResult:
    """PPTX → Markdown 변환 (슬라이드별)"""
    prs = Presentation(io.BytesIO(file_bytes))
    parts: list[str] = []

    for i, slide in enumerate(prs.slides, 1):
        slide_parts: list[str] = [f"## 슬라이드 {i}"]

        for shape in slide.shapes:
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    text = para.text.strip()
                    if text:
                        slide_parts.append(text)
            if shape.has_table:
                table = shape.table
                rows = []
                for row in table.rows:
                    cells = [cell.text.strip() for cell in row.cells]
                    rows.append("| " + " | ".join(cells) + " |")
                if rows:
                    header_sep = "| " + " | ".join(["---"] * len(table.columns)) + " |"
                    rows.insert(1, header_sep)
                    slide_parts.append("\n".join(rows))

        parts.append("\n\n".join(slide_parts))

    full_text = "\n\n---\n\n".join(parts)
    total_chars = len(full_text.strip())
    num_slides = len(prs.slides)

    return ConvertResult(
        text=full_text,
        format="md",
        pages=num_slides,
        file_name=file_name,
        source_format="pptx",
        route="extract",
        quality=Quality(
            total_chars=total_chars,
            chars_per_page=total_chars / num_slides if num_slides > 0 else 0,
            total_pages=num_slides,
            failed_pages=0,
            confidence="high",
        ),
    )
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/test_extractor_pptx.py -v`
Expected: 4 passed

- [ ] **Step 5: extractors/__init__.py에 pptx 등록**

```python
# extractors/__init__.py
from extractors.docx import extract as extract_docx
from extractors.pptx import extract as extract_pptx

EXTRACTORS: dict[str, callable] = {
    "docx": extract_docx,
    "pptx": extract_pptx,
}
```

- [ ] **Step 6: 커밋**

```bash
git add extractors/pptx.py extractors/__init__.py tests/test_extractor_pptx.py
git commit -m "feat: PPTX extractor — slide-by-slide to markdown"
```

---

### Task 7: XLSX Extractor

**Files:**
- Create: `extractors/xlsx.py`
- Create: `tests/test_extractor_xlsx.py`

**SRS 커버:** EXTRACT-04

- [ ] **Step 1: 테스트 작성 — xlsx extractor**

```python
# tests/test_extractor_xlsx.py
import pytest
from extractors.xlsx import extract


@pytest.mark.asyncio
async def test_xlsx_extracts_sheet_names(sample_xlsx_bytes):
    result = await extract(sample_xlsx_bytes, "test.xlsx")
    assert "매출" in result.text
    assert "비용" in result.text


@pytest.mark.asyncio
async def test_xlsx_extracts_data_as_table(sample_xlsx_bytes):
    result = await extract(sample_xlsx_bytes, "test.xlsx")
    assert "월" in result.text
    assert "1000" in result.text
    assert "|" in result.text  # markdown 표 형식


@pytest.mark.asyncio
async def test_xlsx_multiple_sheets(sample_xlsx_bytes):
    result = await extract(sample_xlsx_bytes, "test.xlsx")
    assert "인건비" in result.text
    assert "500" in result.text


@pytest.mark.asyncio
async def test_xlsx_result_metadata(sample_xlsx_bytes):
    result = await extract(sample_xlsx_bytes, "test.xlsx")
    assert result.source_format == "xlsx"
    assert result.route == "extract"
    assert result.pages == 2  # 시트 2개
    assert result.quality.confidence == "high"
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/test_extractor_xlsx.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'extractors.xlsx'`

- [ ] **Step 3: extractors/xlsx.py 구현**

```python
# extractors/xlsx.py
import io
from openpyxl import load_workbook

from models import ConvertResult, Quality


async def extract(file_bytes: bytes, file_name: str) -> ConvertResult:
    """XLSX → Markdown 변환 (시트별 표)"""
    wb = load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
    parts: list[str] = []

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        sheet_parts: list[str] = [f"## {sheet_name}"]

        rows_data = list(ws.iter_rows(values_only=True))
        if not rows_data:
            parts.append("\n\n".join(sheet_parts))
            continue

        # 헤더
        header = [str(c) if c is not None else "" for c in rows_data[0]]
        table_rows = ["| " + " | ".join(header) + " |"]
        table_rows.append("| " + " | ".join(["---"] * len(header)) + " |")

        # 데이터
        for row in rows_data[1:]:
            cells = [str(c) if c is not None else "" for c in row]
            table_rows.append("| " + " | ".join(cells) + " |")

        sheet_parts.append("\n".join(table_rows))
        parts.append("\n\n".join(sheet_parts))

    wb.close()

    full_text = "\n\n---\n\n".join(parts)
    total_chars = len(full_text.strip())
    num_sheets = len(wb.sheetnames)

    return ConvertResult(
        text=full_text,
        format="md",
        pages=num_sheets,
        file_name=file_name,
        source_format="xlsx",
        route="extract",
        quality=Quality(
            total_chars=total_chars,
            chars_per_page=total_chars / num_sheets if num_sheets > 0 else 0,
            total_pages=num_sheets,
            failed_pages=0,
            confidence="high",
        ),
    )
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/test_extractor_xlsx.py -v`
Expected: 4 passed

- [ ] **Step 5: extractors/__init__.py에 xlsx 등록**

```python
# extractors/__init__.py
from extractors.docx import extract as extract_docx
from extractors.pptx import extract as extract_pptx
from extractors.xlsx import extract as extract_xlsx

EXTRACTORS: dict[str, callable] = {
    "docx": extract_docx,
    "pptx": extract_pptx,
    "xlsx": extract_xlsx,
}
```

- [ ] **Step 6: 커밋**

```bash
git add extractors/xlsx.py extractors/__init__.py tests/test_extractor_xlsx.py
git commit -m "feat: XLSX extractor — sheet-by-sheet to markdown tables"
```

---

### Task 8: PDF Extractor + Image Handler

**Files:**
- Create: `extractors/pdf.py`
- Create: `extractors/image.py`
- Create: `tests/test_extractor_pdf.py`
- Create: `tests/test_extractor_image.py`

**SRS 커버:** EXTRACT-05, VLM-01, VLM-04

- [ ] **Step 1: 테스트 작성 — pdf.py**

```python
# tests/test_extractor_pdf.py
import pytest
from extractors.pdf import extract_text, pdf_to_images


@pytest.mark.asyncio
async def test_extract_text_from_text_pdf(tmp_path):
    """텍스트 PDF에서 텍스트 추출 — pypdfium2로 실제 PDF 생성이 어려우므로 mock"""
    from unittest.mock import patch, MagicMock

    mock_page = MagicMock()
    mock_textpage = MagicMock()
    mock_textpage.get_text_range.return_value = "Hello World"
    mock_page.get_textpage.return_value = mock_textpage

    mock_pdf = MagicMock()
    mock_pdf.__len__ = MagicMock(return_value=1)
    mock_pdf.__getitem__ = MagicMock(return_value=mock_page)

    with patch("extractors.pdf.pdfium.PdfDocument", return_value=mock_pdf):
        result = await extract_text(b"fakepdf", "test.pdf")

    assert result.text == "Hello World"
    assert result.source_format == "pdf"
    assert result.route == "extract"
    assert result.pages == 1


@pytest.mark.asyncio
async def test_pdf_to_images():
    """PDF → 이미지 변환 — mock"""
    from unittest.mock import patch, MagicMock

    mock_bitmap = MagicMock()
    mock_pil_image = MagicMock()

    mock_page = MagicMock()
    mock_page.render.return_value = mock_bitmap
    mock_bitmap.to_pil.return_value = mock_pil_image

    mock_pdf = MagicMock()
    mock_pdf.__len__ = MagicMock(return_value=2)
    mock_pdf.__getitem__ = MagicMock(return_value=mock_page)

    with patch("extractors.pdf.pdfium.PdfDocument", return_value=mock_pdf):
        with patch("extractors.pdf._pil_to_bytes", return_value=b"imgdata"):
            images = await pdf_to_images(b"fakepdf")

    assert len(images) == 2
    assert images[0] == b"imgdata"
```

- [ ] **Step 2: 테스트 작성 — image.py**

```python
# tests/test_extractor_image.py
import io
import pytest
from PIL import Image
from extractors.image import prepare_image


@pytest.mark.asyncio
async def test_prepare_image_returns_bytes():
    """이미지 바이트를 받아서 VLM용 바이트로 반환"""
    img = Image.new("RGB", (100, 100), color="red")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    raw = buf.getvalue()

    result = await prepare_image(raw)
    assert isinstance(result, bytes)
    assert len(result) > 0


@pytest.mark.asyncio
async def test_prepare_image_converts_to_png():
    """JPEG 입력도 PNG로 변환"""
    img = Image.new("RGB", (100, 100), color="blue")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    raw = buf.getvalue()

    result = await prepare_image(raw)
    # PNG 매직 바이트 확인
    assert result[:4] == b"\x89PNG"
```

- [ ] **Step 3: 테스트 실패 확인**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/test_extractor_pdf.py tests/test_extractor_image.py -v`
Expected: FAIL

- [ ] **Step 4: extractors/pdf.py 구현**

```python
# extractors/pdf.py
import io

import pypdfium2 as pdfium
from PIL import Image

from models import ConvertResult, Quality


def _pil_to_bytes(pil_image: Image.Image) -> bytes:
    buf = io.BytesIO()
    pil_image.save(buf, format="PNG")
    return buf.getvalue()


async def extract_text(file_bytes: bytes, file_name: str) -> ConvertResult:
    """텍스트 PDF → Markdown (추출 경로)"""
    pdf = pdfium.PdfDocument(file_bytes)
    pages_text: list[str] = []

    for page_index in range(len(pdf)):
        page = pdf[page_index]
        textpage = page.get_textpage()
        text = textpage.get_text_range()
        textpage.close()
        page.close()
        if text.strip():
            pages_text.append(text.strip())

    pdf.close()

    full_text = "\n\n---\n\n".join(pages_text)
    total_chars = len(full_text.strip())
    num_pages = len(pages_text) if pages_text else 1

    return ConvertResult(
        text=full_text,
        format="md",
        pages=num_pages,
        file_name=file_name,
        source_format="pdf",
        route="extract",
        quality=Quality(
            total_chars=total_chars,
            chars_per_page=total_chars / num_pages if num_pages > 0 else 0,
            total_pages=num_pages,
            failed_pages=0,
            confidence="high",
        ),
    )


async def pdf_to_images(file_bytes: bytes, scale: float = 2.0) -> list[bytes]:
    """PDF → 페이지별 PNG 이미지 바이트 리스트"""
    pdf = pdfium.PdfDocument(file_bytes)
    images: list[bytes] = []

    for page_index in range(len(pdf)):
        page = pdf[page_index]
        bitmap = page.render(scale=scale)
        pil_image = bitmap.to_pil()
        images.append(_pil_to_bytes(pil_image))
        page.close()

    pdf.close()
    return images
```

- [ ] **Step 5: extractors/image.py 구현**

```python
# extractors/image.py
import io

from PIL import Image


async def prepare_image(file_bytes: bytes) -> bytes:
    """이미지 바이트를 VLM 전송용 PNG 바이트로 변환"""
    img = Image.open(io.BytesIO(file_bytes))
    if img.mode != "RGB":
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
```

- [ ] **Step 6: 테스트 통과 확인**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/test_extractor_pdf.py tests/test_extractor_image.py -v`
Expected: 4 passed

- [ ] **Step 7: 커밋**

```bash
git add extractors/pdf.py extractors/image.py tests/test_extractor_pdf.py tests/test_extractor_image.py
git commit -m "feat: PDF extractor (text + image) + image handler"
```

---

### Task 9: VLM Client

**Files:**
- Create: `vlm.py`
- Create: `tests/test_vlm.py`

**SRS 커버:** VLM-02, VLM-03, VLM-05

- [ ] **Step 1: 테스트 작성 — vlm.py**

```python
# tests/test_vlm.py
import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from vlm import VLMClient
from config import Config


@pytest.fixture
def vlm_config():
    return Config(
        vlm_url="http://localhost:11434/v1/chat/completions",
        vlm_model="test-model",
        vlm_timeout=10,
        vlm_concurrency=2,
    )


@pytest.fixture
def vlm_client(vlm_config):
    return VLMClient(vlm_config)


@pytest.mark.asyncio
async def test_process_page_success(vlm_client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "# Extracted Text"}}]
    }
    mock_response.raise_for_status = MagicMock()

    with patch.object(vlm_client.client, "post", new_callable=AsyncMock, return_value=mock_response):
        result = await vlm_client.process_page(b"fake_image", 1)

    assert result.success is True
    assert result.text == "# Extracted Text"
    assert result.page == 1
    assert result.error is None


@pytest.mark.asyncio
async def test_process_page_failure(vlm_client):
    with patch.object(vlm_client.client, "post", new_callable=AsyncMock, side_effect=Exception("connection refused")):
        result = await vlm_client.process_page(b"fake_image", 3)

    assert result.success is False
    assert "[변환 실패: 페이지 3]" in result.text
    assert "connection refused" in result.error


@pytest.mark.asyncio
async def test_process_document_all_success(vlm_client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "page text"}}]
    }
    mock_response.raise_for_status = MagicMock()

    with patch.object(vlm_client.client, "post", new_callable=AsyncMock, return_value=mock_response):
        result = await vlm_client.process_document([b"img1", b"img2"])

    assert result.total_pages == 2
    assert result.failed_pages == 0
    assert result.confidence == "high"
    assert "page text" in result.text


@pytest.mark.asyncio
async def test_process_document_partial_failure(vlm_client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "page text"}}]
    }
    mock_response.raise_for_status = MagicMock()

    call_count = 0

    async def mock_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise Exception("timeout")
        return mock_response

    with patch.object(vlm_client.client, "post", side_effect=mock_post):
        result = await vlm_client.process_document([b"img1", b"img2", b"img3"])

    assert result.total_pages == 3
    assert result.failed_pages == 1
    assert result.confidence == "partial"
    assert "[변환 실패: 페이지 2]" in result.text


@pytest.mark.asyncio
async def test_semaphore_limits_concurrency(vlm_client):
    """동시 실행이 vlm_concurrency(2)로 제한되는지 확인"""
    active = 0
    max_active = 0

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "text"}}]
    }
    mock_response.raise_for_status = MagicMock()

    original_process_page = vlm_client.process_page

    async def tracking_post(*args, **kwargs):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.05)
        active -= 1
        return mock_response

    with patch.object(vlm_client.client, "post", side_effect=tracking_post):
        await vlm_client.process_document([b"img"] * 5)

    assert max_active <= 2  # vlm_concurrency = 2


@pytest.mark.asyncio
async def test_vlm_client_close(vlm_client):
    await vlm_client.close()
    # close 호출 후 에러 없이 완료되면 OK
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/test_vlm.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'vlm'`

- [ ] **Step 3: vlm.py 구현**

```python
# vlm.py
import asyncio
import base64

import httpx

from config import Config
from models import PageResult


class DocumentResult:
    def __init__(self, text: str, total_pages: int, failed_pages: int, confidence: str):
        self.text = text
        self.total_pages = total_pages
        self.failed_pages = failed_pages
        self.confidence = confidence


VLM_PROMPT = """이 문서 페이지의 내용을 Markdown으로 변환해.

규칙:
- 모든 텍스트를 레이아웃 순서대로 추출
- 표는 마크다운 표 형식으로 변환
- 이미지/도형은 [이미지: 설명] 형태로 기술
- 제목/소제목은 마크다운 헤딩(#, ##)으로
- 원본 내용을 빠뜨리지 말 것"""


class VLMClient:
    def __init__(self, config: Config):
        self.config = config
        self.client = httpx.AsyncClient(timeout=config.vlm_timeout)
        self.semaphore = asyncio.Semaphore(config.vlm_concurrency)

    async def process_page(self, image_bytes: bytes, page_num: int) -> PageResult:
        """단일 페이지 VLM 호출. 실패 시 예외 안 던짐."""
        async with self.semaphore:
            try:
                b64_image = base64.b64encode(image_bytes).decode("utf-8")
                payload = {
                    "model": self.config.vlm_model,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": VLM_PROMPT},
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/png;base64,{b64_image}"
                                    },
                                },
                            ],
                        }
                    ],
                    "max_tokens": 4096,
                }

                headers = {"Content-Type": "application/json"}
                if self.config.vlm_api_key:
                    headers["Authorization"] = f"Bearer {self.config.vlm_api_key}"

                response = await self.client.post(
                    self.config.vlm_url, json=payload, headers=headers
                )
                response.raise_for_status()
                data = response.json()
                text = data["choices"][0]["message"]["content"]
                return PageResult(page=page_num, text=text, success=True)

            except Exception as e:
                return PageResult(
                    page=page_num,
                    text=f"[변환 실패: 페이지 {page_num}]",
                    success=False,
                    error=str(e),
                )

    async def process_document(self, images: list[bytes]) -> DocumentResult:
        """전체 페이지 동시 처리 (Semaphore로 제한)"""
        tasks = [self.process_page(img, i + 1) for i, img in enumerate(images)]
        results = await asyncio.gather(*tasks)

        text = "\n\n".join(r.text for r in results)
        failed = [r for r in results if not r.success]

        return DocumentResult(
            text=text,
            total_pages=len(results),
            failed_pages=len(failed),
            confidence="high" if not failed else "partial",
        )

    async def close(self):
        await self.client.aclose()
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/test_vlm.py -v`
Expected: 6 passed

- [ ] **Step 5: 커밋**

```bash
git add vlm.py tests/test_vlm.py
git commit -m "feat: VLM client — async with semaphore, partial failure support"
```

---

### Task 10: Worker

**Files:**
- Create: `worker.py`
- Create: `tests/test_worker.py`

**SRS 커버:** API-01 (비동기 처리), API-03 (결과 포맷)

- [ ] **Step 1: 테스트 작성 — worker.py**

```python
# tests/test_worker.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from worker import process_job
from job_store import InMemoryJobStore
from models import JobStatus, ConvertResult, Quality
from config import Config


@pytest.fixture
def store():
    return InMemoryJobStore()


@pytest.fixture
def config():
    return Config()


@pytest.mark.asyncio
async def test_worker_extract_route(store, config):
    """extract 경로 — extractor 호출 → 결과 저장"""
    job = await store.create("test.docx", "docx", "extract")

    mock_result = ConvertResult(
        text="# Hello",
        format="md",
        pages=1,
        file_name="test.docx",
        source_format="docx",
        route="extract",
        quality=Quality(total_chars=7, chars_per_page=7, total_pages=1, failed_pages=0, confidence="high"),
    )

    with patch("worker.EXTRACTORS", {"docx": AsyncMock(return_value=mock_result)}):
        await process_job(job, b"fake_docx_bytes", "extract", store, config)

    updated = await store.get(job.id)
    assert updated.status == JobStatus.COMPLETED
    assert updated.result.text == "# Hello"


@pytest.mark.asyncio
async def test_worker_vlm_route(store, config):
    """vlm 경로 — pdf_to_images + VLMClient 호출"""
    job = await store.create("scan.pdf", "pdf", "vlm")

    mock_doc_result = MagicMock()
    mock_doc_result.text = "# Scanned"
    mock_doc_result.total_pages = 1
    mock_doc_result.failed_pages = 0
    mock_doc_result.confidence = "high"

    with patch("worker.pdf_to_images", new_callable=AsyncMock, return_value=[b"img1"]):
        with patch("worker.VLMClient") as MockVLM:
            mock_instance = AsyncMock()
            mock_instance.process_document = AsyncMock(return_value=mock_doc_result)
            mock_instance.close = AsyncMock()
            MockVLM.return_value = mock_instance

            await process_job(job, b"fake_pdf_bytes", "vlm", store, config)

    updated = await store.get(job.id)
    assert updated.status == JobStatus.COMPLETED
    assert updated.result.text == "# Scanned"


@pytest.mark.asyncio
async def test_worker_vlm_image_route(store, config):
    """vlm 경로 — 이미지 파일은 pdf_to_images 안 거침"""
    job = await store.create("photo.jpg", "jpg", "vlm")

    mock_doc_result = MagicMock()
    mock_doc_result.text = "# Photo"
    mock_doc_result.total_pages = 1
    mock_doc_result.failed_pages = 0
    mock_doc_result.confidence = "high"

    with patch("worker.prepare_image", new_callable=AsyncMock, return_value=b"png_bytes"):
        with patch("worker.VLMClient") as MockVLM:
            mock_instance = AsyncMock()
            mock_instance.process_document = AsyncMock(return_value=mock_doc_result)
            mock_instance.close = AsyncMock()
            MockVLM.return_value = mock_instance

            await process_job(job, b"fake_jpg_bytes", "vlm", store, config)

    updated = await store.get(job.id)
    assert updated.status == JobStatus.COMPLETED


@pytest.mark.asyncio
async def test_worker_handles_error(store, config):
    """extractor 예외 시 job이 failed로 전환"""
    job = await store.create("bad.docx", "docx", "extract")

    with patch("worker.EXTRACTORS", {"docx": AsyncMock(side_effect=Exception("corrupt file"))}):
        await process_job(job, b"bad_bytes", "extract", store, config)

    updated = await store.get(job.id)
    assert updated.status == JobStatus.FAILED
    assert "corrupt file" in updated.error
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/test_worker.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'worker'`

- [ ] **Step 3: worker.py 구현**

```python
# worker.py
from config import Config
from extractors import EXTRACTORS
from extractors.image import prepare_image
from extractors.pdf import pdf_to_images
from job_store import JobStore
from models import ConvertResult, Job, JobStatus, Quality
from vlm import DocumentResult, VLMClient


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
            result = await EXTRACTORS[job.source_format](file_bytes, job.file_name)
            await store.save_result(job.id, result)

        elif route == "vlm":
            # 이미지 준비
            if job.source_format == "pdf":
                images = await pdf_to_images(file_bytes)
            else:
                # jpg, png 등 이미지 파일
                img_bytes = await prepare_image(file_bytes)
                images = [img_bytes]

            # VLM 호출
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
                ),
            )
            await store.save_result(job.id, result)

    except Exception as e:
        await store.save_error(job.id, str(e))
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/test_worker.py -v`
Expected: 4 passed

- [ ] **Step 5: 커밋**

```bash
git add worker.py tests/test_worker.py
git commit -m "feat: async worker — extract/vlm routing with error handling"
```

---

### Task 11: FastAPI App (엔드포인트)

**Files:**
- Create: `app.py`
- Create: `tests/test_app.py`

**SRS 커버:** API-01, API-02, API-03, API-04, API-05, API-06

- [ ] **Step 1: 테스트 작성 — app.py**

```python
# tests/test_app.py
import pytest
import asyncio
from unittest.mock import patch, AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport
from app import create_app
from models import JobStatus


@pytest.fixture
def app():
    return create_app()


@pytest.mark.asyncio
async def test_health(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_convert_returns_job_id(app):
    """POST /convert → job_id 반환"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch("app.process_job", new_callable=AsyncMock):
            resp = await client.post(
                "/convert",
                files={"file": ("test.docx", b"fake_docx_content", "application/octet-stream")},
            )
    assert resp.status_code == 200
    data = resp.json()
    assert "job_id" in data
    assert data["status"] == "queued"


@pytest.mark.asyncio
async def test_convert_unsupported_format(app):
    """지원하지 않는 포맷 → 400"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/convert",
            files={"file": ("test.xyz", b"content", "application/octet-stream")},
        )
    assert resp.status_code == 400
    assert "Unsupported" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_result_not_found(app):
    """존재하지 않는 job_id → 404"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/result/nonexistent-id")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_result_queued(app):
    """queued 상태 job → status만 반환"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch("app.process_job", new_callable=AsyncMock):
            create_resp = await client.post(
                "/convert",
                files={"file": ("test.docx", b"content", "application/octet-stream")},
            )
        job_id = create_resp.json()["job_id"]
        resp = await client.get(f"/result/{job_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("queued", "processing")
    assert data["result"] is None


@pytest.mark.asyncio
async def test_batch_returns_job_ids(app):
    """POST /batch → job_id 리스트 반환"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch("app.process_job", new_callable=AsyncMock):
            resp = await client.post(
                "/batch",
                files=[
                    ("files", ("a.docx", b"content1", "application/octet-stream")),
                    ("files", ("b.xlsx", b"content2", "application/octet-stream")),
                ],
            )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["jobs"]) == 2
    assert all("job_id" in j for j in data["jobs"])


@pytest.mark.asyncio
async def test_batch_partial_unsupported(app):
    """batch에서 일부 파일이 지원 안 되면 해당 파일만 에러"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch("app.process_job", new_callable=AsyncMock):
            resp = await client.post(
                "/batch",
                files=[
                    ("files", ("a.docx", b"content1", "application/octet-stream")),
                    ("files", ("b.xyz", b"content2", "application/octet-stream")),
                ],
            )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["jobs"]) == 2
    ok_job = next(j for j in data["jobs"] if j["file_name"] == "a.docx")
    err_job = next(j for j in data["jobs"] if j["file_name"] == "b.xyz")
    assert "job_id" in ok_job
    assert "error" in err_job
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/test_app.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app'`

- [ ] **Step 3: app.py 구현**

```python
# app.py
import asyncio
from contextlib import asynccontextmanager
from typing import List

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from config import Config
from job_store import InMemoryJobStore, JobStore
from router import UnsupportedFormatError, detect_route
from worker import process_job


def create_app(store: JobStore | None = None, config: Config | None = None) -> FastAPI:
    config = config or Config()
    store = store or InMemoryJobStore()

    app = FastAPI(title="Forge — Document Converter", version="0.1.0")

    # store와 config를 app.state에 저장
    app.state.store = store
    app.state.config = config

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.post("/convert")
    async def convert(file: UploadFile = File(...)):
        file_bytes = await file.read()
        file_name = file.filename or "unknown"

        try:
            route, source_format = detect_route(file_name, file_bytes)
        except UnsupportedFormatError as e:
            raise HTTPException(status_code=400, detail=str(e))

        job = await store.create(file_name, source_format, route)
        asyncio.create_task(process_job(job, file_bytes, route, store, config))

        return {"job_id": job.id, "status": job.status}

    @app.get("/result/{job_id}")
    async def result(job_id: str):
        job = await store.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")

        return {
            "status": job.status,
            "result": job.result.model_dump() if job.result else None,
            "error": job.error,
        }

    @app.post("/batch")
    async def batch(files: List[UploadFile] = File(...)):
        jobs = []
        for file in files:
            file_bytes = await file.read()
            file_name = file.filename or "unknown"

            try:
                route, source_format = detect_route(file_name, file_bytes)
            except UnsupportedFormatError as e:
                jobs.append({"file_name": file_name, "error": str(e)})
                continue

            job = await store.create(file_name, source_format, route)
            asyncio.create_task(process_job(job, file_bytes, route, store, config))
            jobs.append({"file_name": file_name, "job_id": job.id, "status": job.status})

        return {"jobs": jobs}

    return app


app = create_app()
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/test_app.py -v`
Expected: 7 passed

- [ ] **Step 5: 전체 테스트 실행**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/ -v`
Expected: 모든 테스트 통과

- [ ] **Step 6: 커밋**

```bash
git add app.py tests/test_app.py
git commit -m "feat: FastAPI endpoints — /convert, /result, /batch, /health"
```

---

### Task 12: Dockerfile + 인프라 마무리

**Files:**
- Create: `Dockerfile`

- [ ] **Step 1: Dockerfile 작성**

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8003

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8003"]
```

- [ ] **Step 2: 전체 테스트 최종 확인**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/ -v`
Expected: 전체 통과 (약 40+ tests)

- [ ] **Step 3: 커밋**

```bash
git add Dockerfile
git commit -m "feat: Dockerfile for standalone deployment on port 8003"
```

---

## Eng Review 반영사항 (2026-04-07)

### 1A) 예외 로깅 래퍼 (Task 11 app.py 수정)

app.py에서 `asyncio.create_task` 호출 시 래퍼 함수로 감싸기:

```python
# app.py 상단에 추가
import logging

logger = logging.getLogger(__name__)

async def _safe_process(job, file_bytes, route, store, config):
    """create_task용 래퍼. 미처리 예외를 로깅."""
    try:
        await process_job(job, file_bytes, route, store, config)
    except Exception:
        logger.exception("Unhandled error in job %s", job.id)

# create_task 호출부 변경 (convert, batch 둘 다):
# Before: asyncio.create_task(process_job(job, file_bytes, route, store, config))
# After:  asyncio.create_task(_safe_process(job, file_bytes, route, store, config))
```

테스트 추가 (test_app.py):

```python
@pytest.mark.asyncio
async def test_exception_logging_wrapper(app, caplog):
    """worker 최외곽 예외가 로깅되는지 확인"""
    import logging
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch("app.process_job", new_callable=AsyncMock, side_effect=RuntimeError("unexpected")):
            resp = await client.post(
                "/convert",
                files={"file": ("test.docx", b"content", "application/octet-stream")},
            )
    assert resp.status_code == 200  # job_id는 반환됨
    await asyncio.sleep(0.1)  # background task 실행 대기
    # 로그에 에러가 기록되었는지 확인은 통합 테스트에서
```

### 2A) VLM retry + MAX_FILE_SIZE

**VLM retry (vlm.py process_page 수정):**

```python
# vlm.py process_page 내부, self.client.post 호출부를 retry 래핑
import asyncio

MAX_RETRIES = 3
RETRY_DELAYS = [1, 2, 4]  # 지수 백오프

async def process_page(self, image_bytes: bytes, page_num: int) -> PageResult:
    async with self.semaphore:
        last_error = None
        for attempt in range(MAX_RETRIES):
            try:
                # ... 기존 VLM 호출 코드 ...
                response = await self.client.post(self.config.vlm_url, json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
                text = data["choices"][0]["message"]["content"]
                return PageResult(page=page_num, text=text, success=True)
            except Exception as e:
                last_error = e
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_DELAYS[attempt])
        return PageResult(
            page=page_num,
            text=f"[변환 실패: 페이지 {page_num}]",
            success=False,
            error=str(last_error),
        )
```

VLM retry 테스트 추가 (test_vlm.py):

```python
@pytest.mark.asyncio
async def test_retry_then_success(vlm_client):
    """2회 실패 후 3회째 성공"""
    call_count = 0
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
    mock_response.raise_for_status = MagicMock()

    async def flaky_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise Exception("timeout")
        return mock_response

    with patch.object(vlm_client.client, "post", side_effect=flaky_post):
        result = await vlm_client.process_page(b"img", 1)
    assert result.success is True
    assert call_count == 3


@pytest.mark.asyncio
async def test_retry_all_fail(vlm_client):
    """3회 모두 실패"""
    with patch.object(vlm_client.client, "post", new_callable=AsyncMock, side_effect=Exception("down")):
        result = await vlm_client.process_page(b"img", 1)
    assert result.success is False
    assert "[변환 실패: 페이지 1]" in result.text
```

**MAX_FILE_SIZE (config.py + app.py):**

```python
# config.py에 추가
max_file_size: int = 104_857_600  # 100MB

# app.py convert 엔드포인트 상단에 추가
file_bytes = await file.read()
if len(file_bytes) > config.max_file_size:
    raise HTTPException(status_code=413, detail=f"File too large: max {config.max_file_size} bytes")

# app.py batch 엔드포인트에도 동일 체크
```

MAX_FILE_SIZE 테스트 (test_app.py):

```python
@pytest.mark.asyncio
async def test_convert_file_too_large(app):
    """MAX_FILE_SIZE 초과 → 413"""
    # config의 max_file_size를 10바이트로 설정한 앱 생성
    from config import Config
    from job_store import InMemoryJobStore
    from app import create_app
    small_config = Config(max_file_size=10)
    test_app = create_app(config=small_config)
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/convert",
            files={"file": ("test.docx", b"x" * 100, "application/octet-stream")},
        )
    assert resp.status_code == 413
```

### 3A) Job 모델 frozen=False (Task 2 models.py 수정)

```python
# models.py Job 클래스에 추가
from pydantic import ConfigDict

class Job(BaseModel):
    model_config = ConfigDict(frozen=False)
    # ... 기존 필드 동일 ...
```

### 4A) DocumentResult를 models.py로 통합 (Task 2 + Task 9 수정)

```python
# models.py에 추가
class DocumentResult(BaseModel):
    text: str
    total_pages: int
    failed_pages: int
    confidence: str  # "high" | "partial"

# vlm.py에서 제거하고 import로 교체:
from models import DocumentResult, PageResult
```

---

## NOT in scope (v2)

- HWPX 지원 (추후 API 기반)
- hybrid route (페이지 단위 extract→VLM fallback)
- sync mode (?sync=true)
- callback_url
- Job TTL + 자동 정리
- DELETE /jobs/{job_id} (취소)
- POST /retry/{job_id}
- GET /formats
- quality gate (weighted scoring)
- Redis 기반 Job Store (인터페이스만 준비)
- CI/CD 파이프라인
- 파일 스트리밍 (SpooledTemporaryFile) — Redis 전환 시 함께 고려

## What already exists

- **Cortex(:8000):** FastAPI + PostgreSQL + pgvector + AGE. 텍스트 PDF 직접 처리, Docling 기반 청킹. Converter와 독립 — 코드 재사용 대상 없음.
- **office-hours 디자인 문서:** 스코프가 더 넓음 (quality gate, hybrid, retry API 등). 브레인스토밍에서 의도적으로 축소.

## Failure Modes

| 경로 | 실패 시나리오 | 테스트 | 에러 처리 | 사용자 경험 |
|------|-------------|--------|----------|------------|
| VLM 호출 | VLM 서버 다운 | ✅ retry + partial failure | ✅ PageResult.error | 명시적 (confidence: partial) |
| VLM 호출 | 타임아웃 | ✅ retry 테스트 | ✅ 3회 retry 후 실패 기록 | 명시적 |
| 추출 경로 | 손상된 파일 | ✅ worker error 테스트 | ✅ save_error | 명시적 (status: failed) |
| app.py | worker 미처리 예외 | ✅ 래퍼 테스트 | ✅ logging.exception | 로그에 기록 |
| app.py | 100MB 초과 파일 | ✅ 413 테스트 | ✅ HTTPException | 명시적 (413) |
| job_store | save_error 실패 | ❌ | ✅ 래퍼가 로깅 | 로그에 기록 |

Critical gap 0건. save_error 실패는 인메모리 dict이라 사실상 발생 불가.

## Worktree Parallelization Strategy

| Step | Modules touched | Depends on |
|------|----------------|------------|
| Task 1-3 (config, models, job_store) | 기반 모듈 | — |
| Task 4 (router) | router.py | Task 1 (config) |
| Task 5-7 (extractors) | extractors/ | Task 2 (models) |
| Task 8 (pdf+image) | extractors/ | Task 2 (models) |
| Task 9 (VLM) | vlm.py | Task 1-2 (config, models) |
| Task 10 (worker) | worker.py | Task 3,5-9 전부 |
| Task 11 (app) | app.py | Task 3,4,10 |
| Task 12 (Docker) | Dockerfile | Task 11 |

**Lane A:** Task 1→2→3 (기반, 순차)
**Lane B:** Task 5→6→7 (extractors, 순차, models 의존)
**Lane C:** Task 4 (router, 독립)
**Lane D:** Task 8→9 (pdf+vlm, 순차)

Launch: A 먼저 (기반). 완료 후 B+C+D 병렬. 머지 후 Task 10→11→12 순차.

Sequential implementation이 더 안전하지만, B+C+D 병렬화로 시간 절약 가능.

## Spec Coverage Check

| SRS ID | Task | 상태 |
|--------|------|------|
| ROUTE-01~05 | Task 4 | ✅ |
| EXTRACT-01 | Task 5 | ✅ |
| EXTRACT-02 | Task 6 | ✅ |
| EXTRACT-04 | Task 7 | ✅ |
| EXTRACT-05 | Task 8 | ✅ |
| VLM-01 | Task 8 | ✅ |
| VLM-02 | Task 9 | ✅ |
| VLM-03 | Task 9 | ✅ |
| VLM-04 | Task 8 | ✅ |
| VLM-05 | Task 9 | ✅ |
| API-01 | Task 11 | ✅ |
| API-02 | Task 11 | ✅ |
| API-03 | Task 10, 11 | ✅ |
| API-04 | Task 11 | ✅ |
| API-05 | Task 11 | ✅ |
| API-06 | Task 2, 10 | ✅ |
| CONFIG-01~04 | Task 1 | ✅ |
