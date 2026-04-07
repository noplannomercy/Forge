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
