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
