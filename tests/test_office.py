import pytest
from unittest.mock import patch, AsyncMock
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
    mock_exec.assert_called_once()
    call_args = mock_exec.call_args[0]
    assert "soffice" in call_args[0]
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
