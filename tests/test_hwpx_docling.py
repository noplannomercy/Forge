"""T15: HWPX → Docling bridge via LibreOffice DOCX conversion.

docling-serve는 HWPX를 네이티브로 지원하지 않으므로 worker의 docling 경로는
HWPX를 먼저 LibreOffice headless로 DOCX 변환 후 docling_ex에 전달해야 한다.

LibreOffice는 로컬 테스트 환경에 설치되어 있지 않을 수 있으므로(기존 test_office
의 두 테스트가 그 이유로 pre-existing fail) 여기서는 subprocess 호출을 전부
mock 하여 분기 로직과 실패 처리만 검증한다.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from config import Config
from models import ConvertResult, JobStatus, Quality


@pytest.fixture
def config():
    return Config()


def _mock_docling_result(source_format: str, file_name: str, route: str = "docling") -> ConvertResult:
    return ConvertResult(
        text="# Mocked docling output",
        format="md",
        pages=1,
        file_name=file_name,
        source_format=source_format,
        route=route,
        quality=Quality(
            total_chars=24, chars_per_page=24, total_pages=1,
            failed_pages=0, confidence="high", method="docling",
        ),
    )


@pytest.mark.asyncio
async def test_worker_hwpx_docling_uses_libreoffice_bridge(store, config):
    """HWPX + route=docling → convert_hwpx_to_docx 호출 후 docling_extract에 DOCX bytes 전달."""
    from worker import process_job

    job = await store.create("mydoc.hwpx", "hwpx", "docling")

    mock_docx_bytes = b"PK\x03\x04fake-docx-bytes"
    mock_convert = AsyncMock(return_value=mock_docx_bytes)
    # docling_ex가 반환하는 결과는 bridged DOCX 기준으로 돌아오지만 worker가
    # 최종적으로 source_format을 "hwpx"로 복원해야 한다.
    mock_extract = AsyncMock(return_value=_mock_docling_result("docx", "mydoc.docx"))

    with patch("extractors.office.convert_hwpx_to_docx", mock_convert):
        with patch("extractors.docling_ex.extract", mock_extract):
            with patch("worker.MetaExtractor") as MockMeta:
                mock_meta = AsyncMock()
                mock_meta.extract = AsyncMock(return_value={})
                mock_meta.close = AsyncMock()
                MockMeta.return_value = mock_meta
                await process_job(job, b"fake-hwpx-bytes", "docling", store, config)

    # Bridge가 정확히 원본 HWPX bytes로 호출되어야 한다.
    mock_convert.assert_called_once_with(b"fake-hwpx-bytes")

    # docling_extract는 bridged DOCX bytes를 받아야 한다 (원본 HWPX가 아니라).
    assert mock_extract.called
    args, kwargs = mock_extract.call_args
    assert args[0] == mock_docx_bytes
    # 두 번째 positional은 bridged 파일명 (확장자 .docx로 치환됨)
    assert args[1].endswith(".docx")

    # 최종 Job result에는 source_format이 "hwpx"로 복원되고 file_name은 원본 유지.
    updated = await store.get(job.id)
    assert updated.status == JobStatus.COMPLETED
    assert updated.result.source_format == "hwpx"
    assert updated.result.file_name == "mydoc.hwpx"


@pytest.mark.asyncio
async def test_worker_non_hwpx_docling_no_bridge(store, config):
    """PDF + route=docling → bridge 호출하지 않고 바로 docling_extract 호출."""
    from worker import process_job

    job = await store.create("doc.pdf", "pdf", "docling")

    mock_convert = AsyncMock()
    mock_extract = AsyncMock(return_value=_mock_docling_result("pdf", "doc.pdf"))

    with patch("extractors.office.convert_hwpx_to_docx", mock_convert):
        with patch("extractors.docling_ex.extract", mock_extract):
            with patch("worker.MetaExtractor") as MockMeta:
                mock_meta = AsyncMock()
                mock_meta.extract = AsyncMock(return_value={})
                mock_meta.close = AsyncMock()
                MockMeta.return_value = mock_meta
                await process_job(job, b"%PDF-fake", "docling", store, config)

    mock_convert.assert_not_called()
    mock_extract.assert_called_once()
    args, kwargs = mock_extract.call_args
    # PDF는 원본 bytes/name 그대로 전달된다.
    assert args[0] == b"%PDF-fake"
    assert args[1] == "doc.pdf"


@pytest.mark.asyncio
async def test_worker_hwpx_docling_bridge_failure_marks_job_failed(store, config):
    """Bridge 실패 시 Job은 FAILED 상태로 기록되고 docling_extract는 호출되지 않는다."""
    from worker import process_job

    job = await store.create("bad.hwpx", "hwpx", "docling")

    mock_convert = AsyncMock(side_effect=RuntimeError("LibreOffice HWPX→DOCX failed: boom"))
    mock_extract = AsyncMock()

    with patch("extractors.office.convert_hwpx_to_docx", mock_convert):
        with patch("extractors.docling_ex.extract", mock_extract):
            await process_job(job, b"fake-hwpx", "docling", store, config)

    mock_extract.assert_not_called()
    updated = await store.get(job.id)
    assert updated.status == JobStatus.FAILED
    assert "HWPX→DOCX" in updated.error


@pytest.mark.asyncio
async def test_convert_hwpx_to_docx_raises_on_libreoffice_nonzero_exit():
    """soffice가 non-zero를 반환하면 RuntimeError('HWPX→DOCX failed') 발생."""
    from extractors.office import convert_hwpx_to_docx

    mock_proc = MagicMock()
    mock_proc.returncode = 1
    mock_proc.communicate = AsyncMock(return_value=(b"", b"LibreOffice crash"))

    with patch("extractors.office._find_soffice", return_value="soffice"):
        with patch("extractors.office.asyncio.create_subprocess_exec",
                   new=AsyncMock(return_value=mock_proc)):
            with pytest.raises(RuntimeError, match="HWPX→DOCX failed"):
                await convert_hwpx_to_docx(b"fake-hwpx-bytes")


@pytest.mark.asyncio
async def test_convert_hwpx_to_docx_invokes_soffice_with_docx_target():
    """Happy path: soffice가 --convert-to docx 인자로 호출되고 생성된 파일을 읽어 반환한다."""
    import os
    from extractors import office as office_mod

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"", b""))

    # _find_soffice가 실제 path 탐색을 하지 않도록 고정.
    original_exists = os.path.exists
    captured = {}

    def fake_exists(path):
        if path.endswith("input.docx"):
            captured["docx_path"] = path
            return True
        return original_exists(path)

    # open(docx_path) 결과 제공을 위해 실제로 임시 파일을 하나 만들고 patch 해도
    # 되지만 더 단순히 builtins.open을 patch 한다.
    import builtins
    real_open = builtins.open
    written = {}

    def fake_open(path, mode="r", *args, **kwargs):
        if mode == "wb" and str(path).endswith("input.hwpx"):
            class _Sink:
                def write(self, data):
                    written["hwpx"] = data
                def __enter__(self): return self
                def __exit__(self, *a): pass
            return _Sink()
        if mode == "rb" and str(path).endswith("input.docx"):
            class _Src:
                def read(self):
                    return b"PK\x03\x04docx-output"
                def __enter__(self): return self
                def __exit__(self, *a): pass
            return _Src()
        return real_open(path, mode, *args, **kwargs)

    with patch.object(office_mod, "_find_soffice", return_value="soffice"):
        with patch.object(office_mod.asyncio, "create_subprocess_exec",
                          new=AsyncMock(return_value=mock_proc)) as mock_exec:
            with patch.object(office_mod.os.path, "exists", side_effect=fake_exists):
                with patch.object(builtins, "open", side_effect=fake_open):
                    result = await office_mod.convert_hwpx_to_docx(b"hwpx-input-bytes")

    assert result == b"PK\x03\x04docx-output"
    assert written["hwpx"] == b"hwpx-input-bytes"

    # soffice가 docx target으로 호출됐는지 확인.
    call_args = mock_exec.call_args[0]
    assert "soffice" in call_args[0]
    assert "--headless" in call_args
    assert "--convert-to" in call_args
    assert "docx" in call_args
