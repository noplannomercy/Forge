import pytest
from router import detect_route, UnsupportedFormatError


def test_docx_routes_to_extract():
    route, fmt = detect_route("report.docx", b"dummy")
    assert route == "extract"
    assert fmt == "docx"


def test_pptx_routes_to_vlm():
    route, fmt = detect_route("slides.pptx", b"dummy")
    assert route == "vlm"
    assert fmt == "pptx"


def test_route_override_forces_vlm():
    route, fmt = detect_route("report.docx", b"dummy", route_override="vlm")
    assert route == "vlm"
    assert fmt == "docx"


def test_route_override_pptx_extract_raises():
    """PPTX는 extract 강제 불가"""
    with pytest.raises(UnsupportedFormatError, match="PPTX"):
        detect_route("slides.pptx", b"dummy", route_override="extract")


def test_route_override_forces_extract_on_docx():
    route, fmt = detect_route("report.docx", b"dummy", route_override="extract")
    assert route == "extract"
    assert fmt == "docx"


def test_route_override_forces_extract_on_image():
    route, fmt = detect_route("photo.png", b"dummy", route_override="extract")
    assert route == "extract"
    assert fmt == "png"


def test_route_override_none_uses_default():
    route, fmt = detect_route("data.xlsx", b"dummy", route_override=None)
    assert route == "extract"
    assert fmt == "xlsx"


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


def test_hwpx_routes_to_docling():
    """v3: HWPX는 DOCX bridge(T15)를 통해 docling으로 변환된다."""
    route, fmt = detect_route("문서.hwpx", b"dummy")
    assert route == "docling"
    assert fmt == "hwpx"


def test_case_insensitive():
    route, fmt = detect_route("REPORT.DOCX", b"dummy")
    assert route == "extract"
    assert fmt == "docx"


def test_pdf_with_text_routes_to_docling(tmp_path):
    """v3: 텍스트가 충분한 PDF → docling 경로 (기본값이 extract → docling으로 변경)"""
    from unittest.mock import patch
    with patch("router.try_extract_pdf_text", return_value=5000):
        route, fmt = detect_route("report.pdf", b"fakepdf")
    assert route == "docling"
    assert fmt == "pdf"


def test_pdf_scan_routes_to_vlm():
    """텍스트가 거의 없는 PDF → vlm 경로 (변경 없음)"""
    from unittest.mock import patch
    with patch("router.try_extract_pdf_text", return_value=50):
        route, fmt = detect_route("scan.pdf", b"fakepdf")
    assert route == "vlm"
    assert fmt == "pdf"


def test_pdf_override_extract():
    """route_override=extract 시 PDF는 extract로 강제."""
    from unittest.mock import patch
    with patch("router.try_extract_pdf_text", return_value=5000):
        route, fmt = detect_route("report.pdf", b"fakepdf", route_override="extract")
    assert route == "extract"
    assert fmt == "pdf"


def test_pdf_override_docling_on_scan():
    """route_override=docling 시 스캔 PDF도 docling으로 강제."""
    from unittest.mock import patch
    with patch("router.try_extract_pdf_text", return_value=50):
        route, fmt = detect_route("scan.pdf", b"fakepdf", route_override="docling")
    assert route == "docling"
    assert fmt == "pdf"


def test_route_override_docling_on_docx():
    """route_override=docling 시 DOCX도 docling으로 강제."""
    route, fmt = detect_route("report.docx", b"dummy", route_override="docling")
    assert route == "docling"
    assert fmt == "docx"


def test_hwpx_override_extract():
    """route_override=extract 시 HWPX는 extract로 강제 (기본 docling을 우회)."""
    route, fmt = detect_route("문서.hwpx", b"dummy", route_override="extract")
    assert route == "extract"
    assert fmt == "hwpx"
