# Forge Semantic VLM Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** VLM 경로를 페이지별 OCR에서 배치 단위 semantic 재구성으로 교체하고, PPTX를 LibreOffice headless → PDF → VLM 파이프라인으로 처리한다.

**Architecture:** 기존 VLM 파이프라인(페이지별 process_page)을 배치 단위 process_batch로 교체. PPTX는 LibreOffice headless로 PDF 변환 후 기존 PDF→이미지 파이프라인에 합류. 라우터에 route 파라미터 추가로 강제 지정 가능.

**Tech Stack:** Python 3.11, FastAPI, httpx, pypdfium2, LibreOffice headless, pytest, pytest-asyncio

---

## File Map

| 파일 | 역할 | Task |
|------|------|------|
| `config.py` | `vlm_batch_size` 추가 | 1 |
| `models.py` | Quality에 `total_batches`, `failed_batches`, `method` 추가, DocumentResult에 배치 정보 추가 | 1 |
| `vlm.py` | `process_page` → `process_batch` (멀티 이미지 + semantic 프롬프트), `process_document` 배치 청크 | 2 |
| `extractors/office.py` | 신규 — LibreOffice headless PPTX→PDF 래퍼 | 3 |
| `router.py` | PPTX를 VLM으로 이동, `route_override` 파라미터 지원 | 4 |
| `worker.py` | PPTX→PDF→이미지→VLM 파이프라인, semantic 결과 조립 | 5 |
| `app.py` | `route` 쿼리 파라미터 추가 | 6 |
| `extractors/__init__.py` | PPTX extractor 제거 | 5 |
| `.env.example` | `VLM_BATCH_SIZE=5` 추가 | 1 |
| `Dockerfile` | `libreoffice-core` 설치 추가 | 7 |
| `tests/` | 각 Task별 테스트 | 1-7 |

---

### Task 1: Config + Models 확장

**Files:**
- Modify: `config.py`
- Modify: `models.py`
- Modify: `.env.example`
- Modify: `tests/test_config.py`
- Modify: `tests/test_models.py`

- [ ] **Step 1: 테스트 작성 — config.py 확장**

```python
# tests/test_config.py 에 추가
def test_config_vlm_batch_size_default():
    config = Config()
    assert config.vlm_batch_size == 5


def test_config_vlm_batch_size_from_env(monkeypatch):
    monkeypatch.setenv("VLM_BATCH_SIZE", "10")
    config = Config()
    assert config.vlm_batch_size == 10
```

- [ ] **Step 2: 테스트 작성 — models.py 확장**

```python
# tests/test_models.py 에 추가
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
    dr = DocumentResult(
        text="# Title", total_pages=10, failed_pages=0,
        confidence="high", total_batches=2, failed_batches=0,
    )
    assert dr.total_batches == 2
    assert dr.failed_batches == 0
```

- [ ] **Step 3: 테스트 실패 확인**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/test_config.py tests/test_models.py -v`
Expected: FAIL — `unexpected keyword argument 'vlm_batch_size'`, `unexpected keyword argument 'total_batches'`

- [ ] **Step 4: config.py 구현**

```python
# config.py
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    vlm_url: str = "http://localhost:11434/v1/chat/completions"
    vlm_model: str = "qwen2-vl:7b"
    vlm_api_key: str = ""
    vlm_timeout: int = 120
    vlm_concurrency: int = 3
    vlm_batch_size: int = 5
    host: str = "0.0.0.0"
    port: int = 8003
    max_file_size: int = 104_857_600  # 100MB

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")
```

- [ ] **Step 5: models.py 구현 — Quality 확장**

Quality에 3개 필드 추가 (기본값 있어서 기존 코드 호환):

```python
class Quality(BaseModel):
    total_chars: int
    chars_per_page: float
    total_pages: int
    failed_pages: int
    confidence: str  # "high" | "partial"
    total_batches: int = 0
    failed_batches: int = 0
    method: str = "extract"  # "extract" | "semantic"
```

DocumentResult에 배치 필드 추가:

```python
class DocumentResult(BaseModel):
    text: str
    total_pages: int
    failed_pages: int
    confidence: str  # "high" | "partial"
    total_batches: int = 0
    failed_batches: int = 0
```

- [ ] **Step 6: .env.example 업데이트**

`.env.example` 끝에 추가:
```
VLM_BATCH_SIZE=5
```

- [ ] **Step 7: 테스트 통과 확인**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/test_config.py tests/test_models.py -v`
Expected: 모든 테스트 통과

- [ ] **Step 8: 커밋**

```bash
git add config.py models.py .env.example tests/test_config.py tests/test_models.py
git commit -m "feat: add vlm_batch_size config + Quality/DocumentResult batch fields"
```

---

### Task 2: VLM Client — Semantic 배치 모드

**Files:**
- Modify: `vlm.py`
- Modify: `tests/test_vlm.py`

- [ ] **Step 1: 테스트 작성 — vlm.py semantic 배치**

```python
# tests/test_vlm.py — 기존 테스트 교체
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
        vlm_batch_size=3,
    )


@pytest.fixture
def vlm_client(vlm_config):
    return VLMClient(vlm_config)


@pytest.mark.asyncio
async def test_process_batch_success(vlm_client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "## Section 1\nReconstructed content"}}]
    }
    mock_response.raise_for_status = MagicMock()

    with patch.object(vlm_client.client, "post", new_callable=AsyncMock, return_value=mock_response):
        result = await vlm_client.process_batch([b"img1", b"img2", b"img3"], batch_num=1)

    assert result.success is True
    assert "Reconstructed content" in result.text
    assert result.batch_num == 1
    assert result.error is None


@pytest.mark.asyncio
async def test_process_batch_failure_after_retries(vlm_client):
    with patch.object(vlm_client.client, "post", new_callable=AsyncMock, side_effect=Exception("timeout")):
        with patch("vlm.asyncio.sleep", new_callable=AsyncMock):
            result = await vlm_client.process_batch([b"img1", b"img2"], batch_num=2)

    assert result.success is False
    assert "[변환 실패: 페이지" in result.text
    assert result.batch_num == 2
    assert "timeout" in result.error


@pytest.mark.asyncio
async def test_process_batch_retry_then_success(vlm_client):
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
        with patch("vlm.asyncio.sleep", new_callable=AsyncMock):
            result = await vlm_client.process_batch([b"img1"], batch_num=1)

    assert result.success is True
    assert call_count == 3


@pytest.mark.asyncio
async def test_process_document_batches_correctly(vlm_client):
    """9 images with batch_size=3 → 3 batches"""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "batch text"}}]
    }
    mock_response.raise_for_status = MagicMock()

    with patch.object(vlm_client.client, "post", new_callable=AsyncMock, return_value=mock_response):
        result = await vlm_client.process_document([b"img"] * 9)

    assert result.total_pages == 9
    assert result.total_batches == 3
    assert result.failed_batches == 0
    assert result.confidence == "high"
    assert "batch text" in result.text


@pytest.mark.asyncio
async def test_process_document_partial_batch_failure(vlm_client):
    """3 batches, 2nd fails → partial"""
    call_count = 0
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "batch text"}}]
    }
    mock_response.raise_for_status = MagicMock()

    async def mock_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        # batch 2 fails (calls 4,5,6 are retries for batch 2)
        if call_count in (2, 5, 8):
            raise Exception("timeout")
        return mock_response

    with patch.object(vlm_client.client, "post", side_effect=mock_post):
        with patch("vlm.asyncio.sleep", new_callable=AsyncMock):
            result = await vlm_client.process_document([b"img"] * 9)

    assert result.total_batches == 3
    assert result.failed_batches == 1
    assert result.confidence == "partial"
    assert "[변환 실패:" in result.text


@pytest.mark.asyncio
async def test_semaphore_limits_concurrent_batches(vlm_client):
    active = 0
    max_active = 0

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "text"}}]
    }
    mock_response.raise_for_status = MagicMock()

    async def tracking_post(*args, **kwargs):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.05)
        active -= 1
        return mock_response

    with patch.object(vlm_client.client, "post", side_effect=tracking_post):
        await vlm_client.process_document([b"img"] * 15)  # 5 batches of 3

    assert max_active <= 2  # vlm_concurrency = 2


@pytest.mark.asyncio
async def test_vlm_client_close(vlm_client):
    await vlm_client.close()
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/test_vlm.py -v`
Expected: FAIL — `process_batch` not found

- [ ] **Step 3: vlm.py 구현**

```python
# vlm.py
import asyncio
import base64

import httpx

from config import Config
from models import DocumentResult

MAX_RETRIES = 3
RETRY_DELAYS = [1, 2, 4]  # 지수 백오프


SEMANTIC_PROMPT = """이 문서 페이지들을 분석해서 의미 중심으로 재구성해.

규칙:
- 페이지별로 나누지 말고, 내용을 주제별로 묶어서 구조화
- 배경 이미지, 장식, 페이지 번호 등 의미 없는 요소는 무시
- 다이어그램/흐름도는 텍스트로 설명
- 표/비교 데이터는 마크다운 표로 재구성
- 핵심 정보만 추출해서 간결한 마크다운 문서로 만들어
- 한국어로 작성"""


class BatchResult:
    def __init__(self, batch_num: int, text: str, success: bool, error: str | None = None):
        self.batch_num = batch_num
        self.text = text
        self.success = success
        self.error = error


class VLMClient:
    def __init__(self, config: Config):
        self.config = config
        self.client = httpx.AsyncClient(timeout=config.vlm_timeout)
        self.semaphore = asyncio.Semaphore(config.vlm_concurrency)

    async def process_batch(self, images: list[bytes], batch_num: int) -> BatchResult:
        """N장 이미지를 묶어서 semantic 프롬프트로 1회 VLM 호출. 3회 retry."""
        async with self.semaphore:
            last_error = None
            for attempt in range(MAX_RETRIES):
                try:
                    content = [{"type": "text", "text": SEMANTIC_PROMPT}]
                    for img in images:
                        b64 = base64.b64encode(img).decode("utf-8")
                        content.append({
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{b64}"},
                        })

                    payload = {
                        "model": self.config.vlm_model,
                        "messages": [{"role": "user", "content": content}],
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
                    return BatchResult(batch_num=batch_num, text=text, success=True)

                except Exception as e:
                    last_error = e
                    if attempt < MAX_RETRIES - 1:
                        await asyncio.sleep(RETRY_DELAYS[attempt])

            start_page = (batch_num - 1) * self.config.vlm_batch_size + 1
            end_page = start_page + len(images) - 1
            return BatchResult(
                batch_num=batch_num,
                text=f"[변환 실패: 페이지 {start_page}-{end_page}]",
                success=False,
                error=str(last_error),
            )

    async def process_document(self, images: list[bytes]) -> DocumentResult:
        """전체 이미지를 batch_size씩 나눠서 semantic 처리."""
        batch_size = self.config.vlm_batch_size
        batches = [images[i:i + batch_size] for i in range(0, len(images), batch_size)]

        tasks = [
            self.process_batch(batch, batch_num=i + 1)
            for i, batch in enumerate(batches)
        ]
        results = await asyncio.gather(*tasks)

        text = "\n\n---\n\n".join(r.text for r in results)
        failed = [r for r in results if not r.success]

        return DocumentResult(
            text=text,
            total_pages=len(images),
            failed_pages=0,
            confidence="high" if not failed else "partial",
            total_batches=len(batches),
            failed_batches=len(failed),
        )

    async def close(self):
        await self.client.aclose()
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/test_vlm.py -v`
Expected: 7 passed

- [ ] **Step 5: 커밋**

```bash
git add vlm.py tests/test_vlm.py
git commit -m "feat: semantic batch VLM — multi-image per request with retry"
```

---

### Task 3: LibreOffice Headless 래퍼

**Files:**
- Create: `extractors/office.py`
- Create: `tests/test_office.py`

- [ ] **Step 1: 테스트 작성 — office.py**

```python
# tests/test_office.py
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from extractors.office import pptx_to_pdf


@pytest.mark.asyncio
async def test_pptx_to_pdf_calls_libreoffice():
    """LibreOffice headless가 호출되는지 확인"""
    mock_process = AsyncMock()
    mock_process.returncode = 0
    mock_process.communicate = AsyncMock(return_value=(b"", b""))

    with patch("extractors.office.asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec:
        with patch("extractors.office._read_and_cleanup", return_value=b"%PDF-fake"):
            result = await pptx_to_pdf(b"fake_pptx_bytes")

    assert result == b"%PDF-fake"
    # libreoffice가 호출됐는지 확인
    mock_exec.assert_called_once()
    call_args = mock_exec.call_args[0]
    assert "libreoffice" in call_args[0] or "soffice" in call_args[0]
    assert "--headless" in call_args
    assert "--convert-to" in call_args
    assert "pdf" in call_args


@pytest.mark.asyncio
async def test_pptx_to_pdf_raises_on_failure():
    """LibreOffice 실패 시 예외"""
    mock_process = AsyncMock()
    mock_process.returncode = 1
    mock_process.communicate = AsyncMock(return_value=(b"", b"Error converting"))

    with patch("extractors.office.asyncio.create_subprocess_exec", return_value=mock_process):
        with pytest.raises(RuntimeError, match="LibreOffice"):
            await pptx_to_pdf(b"fake_pptx_bytes")
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/test_office.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'extractors.office'`

- [ ] **Step 3: extractors/office.py 구현**

```python
# extractors/office.py
import asyncio
import os
import shutil
import tempfile


async def _read_and_cleanup(pdf_path: str, tmpdir: str) -> bytes:
    """PDF 파일 읽고 임시 디렉토리 정리"""
    try:
        with open(pdf_path, "rb") as f:
            return f.read()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


async def pptx_to_pdf(file_bytes: bytes) -> bytes:
    """PPTX → PDF 변환 (LibreOffice headless)"""
    tmpdir = tempfile.mkdtemp()
    input_path = os.path.join(tmpdir, "input.pptx")

    with open(input_path, "wb") as f:
        f.write(file_bytes)

    process = await asyncio.create_subprocess_exec(
        "soffice", "--headless", "--convert-to", "pdf",
        "--outdir", tmpdir, input_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()

    if process.returncode != 0:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise RuntimeError(f"LibreOffice conversion failed: {stderr.decode()}")

    pdf_path = os.path.join(tmpdir, "input.pdf")
    return await _read_and_cleanup(pdf_path, tmpdir)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/test_office.py -v`
Expected: 2 passed

- [ ] **Step 5: 커밋**

```bash
git add extractors/office.py tests/test_office.py
git commit -m "feat: LibreOffice headless wrapper — PPTX to PDF conversion"
```

---

### Task 4: Router — PPTX → VLM + route 파라미터

**Files:**
- Modify: `router.py`
- Modify: `tests/test_router.py`

- [ ] **Step 1: 테스트 작성 — router.py 변경**

```python
# tests/test_router.py 에 추가/변경

def test_pptx_routes_to_vlm():
    """PPTX는 이제 VLM 경로"""
    route, fmt = detect_route("slides.pptx", b"dummy")
    assert route == "vlm"
    assert fmt == "pptx"


def test_route_override_forces_vlm():
    """route_override로 DOCX도 VLM 강제"""
    route, fmt = detect_route("report.docx", b"dummy", route_override="vlm")
    assert route == "vlm"
    assert fmt == "docx"


def test_route_override_forces_extract():
    """route_override로 PPTX도 extract 강제"""
    route, fmt = detect_route("slides.pptx", b"dummy", route_override="extract")
    assert route == "extract"
    assert fmt == "pptx"


def test_route_override_forces_extract_on_image():
    """route_override로 이미지도 extract 강제 (비권장이지만 가능)"""
    route, fmt = detect_route("photo.png", b"dummy", route_override="extract")
    assert route == "extract"
    assert fmt == "png"


def test_route_override_none_uses_default():
    """route_override=None이면 기존 로직"""
    route, fmt = detect_route("data.xlsx", b"dummy", route_override=None)
    assert route == "extract"
    assert fmt == "xlsx"
```

- [ ] **Step 2: 기존 test_pptx_routes_to_extract 테스트 삭제**

`tests/test_router.py`에서 `test_pptx_routes_to_extract` 함수를 삭제한다 (PPTX가 더 이상 extract가 아니므로).

- [ ] **Step 3: 테스트 실패 확인**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/test_router.py -v`
Expected: FAIL — `detect_route() got an unexpected keyword argument 'route_override'`

- [ ] **Step 4: router.py 구현**

```python
# router.py
from pathlib import Path

import pypdfium2 as pdfium


class UnsupportedFormatError(Exception):
    pass


EXTRACT_FORMATS = {".docx", ".xlsx"}
VLM_FORMATS = {".jpg", ".jpeg", ".png", ".tiff", ".bmp", ".pptx"}


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


def detect_route(
    file_name: str,
    file_bytes: bytes,
    route_override: str | None = None,
) -> tuple[str, str]:
    """파일명과 바이트로 처리 경로 결정. (route, source_format) 반환."""
    ext = Path(file_name).suffix.lower()

    # 포맷 확인
    if ext in EXTRACT_FORMATS:
        fmt = ext[1:]
    elif ext in VLM_FORMATS:
        fmt = ext[1:]
    elif ext == ".pdf":
        fmt = "pdf"
    else:
        raise UnsupportedFormatError(f"Unsupported format: {ext}")

    # route_override가 있으면 강제 지정
    if route_override in ("extract", "vlm"):
        return (route_override, fmt)

    # 기본 라우팅
    if ext in EXTRACT_FORMATS:
        return ("extract", fmt)

    if ext in VLM_FORMATS:
        return ("vlm", fmt)

    if ext == ".pdf":
        chars_per_mb = try_extract_pdf_text(file_bytes)
        if chars_per_mb < 100:
            return ("vlm", "pdf")
        return ("extract", "pdf")

    raise UnsupportedFormatError(f"Unsupported format: {ext}")
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/test_router.py -v`
Expected: 모든 테스트 통과

- [ ] **Step 6: 커밋**

```bash
git add router.py tests/test_router.py
git commit -m "feat: PPTX routes to VLM + route_override parameter"
```

---

### Task 5: Worker — PPTX 파이프라인 + semantic 결과 조립

**Files:**
- Modify: `worker.py`
- Modify: `extractors/__init__.py`
- Modify: `tests/test_worker.py`

- [ ] **Step 1: extractors/__init__.py에서 PPTX 제거**

```python
# extractors/__init__.py
from collections.abc import Callable

from extractors.docx import extract as extract_docx
from extractors.xlsx import extract as extract_xlsx

EXTRACTORS: dict[str, Callable] = {
    "docx": extract_docx,
    "xlsx": extract_xlsx,
}
```

- [ ] **Step 2: 테스트 작성 — worker.py 변경**

```python
# tests/test_worker.py — 전체 교체
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from worker import process_job
from job_store import InMemoryJobStore
from models import JobStatus, ConvertResult, Quality, DocumentResult
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
        quality=Quality(total_chars=7, chars_per_page=7, total_pages=1, failed_pages=0, confidence="high", method="extract"),
    )

    with patch("worker.EXTRACTORS", {"docx": AsyncMock(return_value=mock_result)}):
        await process_job(job, b"fake_docx_bytes", "extract", store, config)

    updated = await store.get(job.id)
    assert updated.status == JobStatus.COMPLETED
    assert updated.result.text == "# Hello"
    assert updated.result.quality.method == "extract"


@pytest.mark.asyncio
async def test_worker_vlm_pdf_route(store, config):
    """vlm 경로 — PDF → images → semantic VLM"""
    job = await store.create("scan.pdf", "pdf", "vlm")

    mock_doc_result = DocumentResult(
        text="# Scanned", total_pages=5, failed_pages=0,
        confidence="high", total_batches=1, failed_batches=0,
    )

    with patch("worker.pdf_to_images", new_callable=AsyncMock, return_value=[b"img"] * 5):
        with patch("worker.VLMClient") as MockVLM:
            mock_instance = AsyncMock()
            mock_instance.process_document = AsyncMock(return_value=mock_doc_result)
            mock_instance.close = AsyncMock()
            MockVLM.return_value = mock_instance
            await process_job(job, b"fake_pdf_bytes", "vlm", store, config)

    updated = await store.get(job.id)
    assert updated.status == JobStatus.COMPLETED
    assert updated.result.quality.method == "semantic"
    assert updated.result.quality.total_batches == 1


@pytest.mark.asyncio
async def test_worker_vlm_pptx_route(store, config):
    """vlm 경로 — PPTX → LibreOffice → PDF → images → semantic VLM"""
    job = await store.create("slides.pptx", "pptx", "vlm")

    mock_doc_result = DocumentResult(
        text="# Slides", total_pages=3, failed_pages=0,
        confidence="high", total_batches=1, failed_batches=0,
    )

    with patch("worker.pptx_to_pdf", new_callable=AsyncMock, return_value=b"fake_pdf"):
        with patch("worker.pdf_to_images", new_callable=AsyncMock, return_value=[b"img"] * 3):
            with patch("worker.VLMClient") as MockVLM:
                mock_instance = AsyncMock()
                mock_instance.process_document = AsyncMock(return_value=mock_doc_result)
                mock_instance.close = AsyncMock()
                MockVLM.return_value = mock_instance
                await process_job(job, b"fake_pptx_bytes", "vlm", store, config)

    updated = await store.get(job.id)
    assert updated.status == JobStatus.COMPLETED
    assert updated.result.text == "# Slides"
    assert updated.result.quality.method == "semantic"


@pytest.mark.asyncio
async def test_worker_vlm_image_route(store, config):
    """vlm 경로 — 이미지 단건"""
    job = await store.create("photo.jpg", "jpg", "vlm")

    mock_doc_result = DocumentResult(
        text="# Photo", total_pages=1, failed_pages=0,
        confidence="high", total_batches=1, failed_batches=0,
    )

    with patch("worker.prepare_image", new_callable=AsyncMock, return_value=b"png_bytes"):
        with patch("worker.VLMClient") as MockVLM:
            mock_instance = AsyncMock()
            mock_instance.process_document = AsyncMock(return_value=mock_doc_result)
            mock_instance.close = AsyncMock()
            MockVLM.return_value = mock_instance
            await process_job(job, b"fake_jpg_bytes", "vlm", store, config)

    updated = await store.get(job.id)
    assert updated.status == JobStatus.COMPLETED
    assert updated.result.quality.method == "semantic"


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

- [ ] **Step 3: 테스트 실패 확인**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/test_worker.py -v`
Expected: FAIL

- [ ] **Step 4: worker.py 구현**

```python
# worker.py
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
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/test_worker.py -v`
Expected: 5 passed

- [ ] **Step 6: 커밋**

```bash
git add worker.py extractors/__init__.py tests/test_worker.py
git commit -m "feat: worker PPTX pipeline + semantic quality metadata"
```

---

### Task 6: API — route 쿼리 파라미터

**Files:**
- Modify: `app.py`
- Modify: `tests/test_app.py`

- [ ] **Step 1: 테스트 작성 — route 파라미터**

```python
# tests/test_app.py 에 추가

@pytest.mark.asyncio
async def test_convert_with_route_override(app):
    """?route=vlm으로 DOCX도 VLM 강제"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch("app.process_job", new_callable=AsyncMock):
            resp = await client.post(
                "/convert?route=vlm",
                files={"file": ("test.docx", b"content", "application/octet-stream")},
            )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "queued"


@pytest.mark.asyncio
async def test_convert_with_invalid_route(app):
    """잘못된 route 값 → 무시 (자동 감지)"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch("app.process_job", new_callable=AsyncMock):
            resp = await client.post(
                "/convert?route=invalid",
                files={"file": ("test.docx", b"content", "application/octet-stream")},
            )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_batch_with_route_override(app):
    """batch도 route 파라미터 지원"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch("app.process_job", new_callable=AsyncMock):
            resp = await client.post(
                "/batch?route=vlm",
                files=[
                    ("files", ("a.docx", b"content1", "application/octet-stream")),
                ],
            )
    assert resp.status_code == 200
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/test_app.py -v -k "route"`
Expected: FAIL (route 파라미터 무시됨, 기존 로직으로 동작)

- [ ] **Step 3: app.py 구현**

`app.py`의 `convert`와 `batch` 엔드포인트에 `route` 쿼리 파라미터 추가:

```python
# app.py
import asyncio
import logging
from typing import List

from fastapi import FastAPI, File, HTTPException, Query, UploadFile

from config import Config
from job_store import InMemoryJobStore, JobStore
from router import UnsupportedFormatError, detect_route
from worker import process_job

logger = logging.getLogger(__name__)


async def _safe_process(job, file_bytes, route, store, config):
    """create_task용 래퍼. 미처리 예외를 로깅."""
    try:
        await process_job(job, file_bytes, route, store, config)
    except Exception:
        logger.exception("Unhandled error in job %s", job.id)


def create_app(store: JobStore | None = None, config: Config | None = None) -> FastAPI:
    config = config or Config()
    store = store or InMemoryJobStore()

    app = FastAPI(title="Forge — Document Converter", version="0.2.0")

    app.state.store = store
    app.state.config = config

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.post("/convert")
    async def convert(
        file: UploadFile = File(...),
        route: str | None = Query(None, regex="^(extract|vlm)$"),
    ):
        file_bytes = await file.read()
        file_name = file.filename or "unknown"

        if len(file_bytes) > config.max_file_size:
            raise HTTPException(status_code=413, detail=f"File too large: max {config.max_file_size} bytes")

        try:
            detected_route, source_format = detect_route(file_name, file_bytes, route_override=route)
        except UnsupportedFormatError as e:
            raise HTTPException(status_code=400, detail=str(e))

        job = await store.create(file_name, source_format, detected_route)
        asyncio.create_task(_safe_process(job, file_bytes, detected_route, store, config))

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
    async def batch(
        files: List[UploadFile] = File(...),
        route: str | None = Query(None, regex="^(extract|vlm)$"),
    ):
        jobs = []
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

            job = await store.create(file_name, source_format, detected_route)
            asyncio.create_task(_safe_process(job, file_bytes, detected_route, store, config))
            jobs.append({"file_name": file_name, "job_id": job.id, "status": job.status})

        return {"jobs": jobs}

    return app


app = create_app()
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/test_app.py -v`
Expected: 모든 테스트 통과

- [ ] **Step 5: 전체 테스트 실행**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/ -v`
Expected: 전체 통과

- [ ] **Step 6: 커밋**

```bash
git add app.py tests/test_app.py
git commit -m "feat: route query parameter for forced extract/vlm routing"
```

---

### Task 7: Dockerfile + 최종 검증

**Files:**
- Modify: `Dockerfile`

- [ ] **Step 1: Dockerfile 업데이트**

```dockerfile
FROM python:3.11-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends libreoffice-core && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8003

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8003"]
```

- [ ] **Step 2: 전체 테스트 최종 확인**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/ -v`
Expected: 전체 통과

- [ ] **Step 3: 커밋**

```bash
git add Dockerfile
git commit -m "feat: Dockerfile with LibreOffice headless for PPTX conversion"
```

---
