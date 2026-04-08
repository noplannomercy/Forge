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


def detect_route(file_name: str, file_bytes: bytes, route_override: str | None = None) -> tuple[str, str]:
    """파일명과 바이트로 처리 경로 결정. (route, source_format) 반환."""
    ext = Path(file_name).suffix.lower()

    if ext in EXTRACT_FORMATS:
        fmt = ext[1:]
    elif ext in VLM_FORMATS:
        fmt = ext[1:]
    elif ext == ".pdf":
        fmt = "pdf"
    else:
        raise UnsupportedFormatError(f"Unsupported format: {ext}")

    if route_override in ("extract", "vlm"):
        # PPTX는 extract 불가 (VLM only — extractors에서 제거됨)
        if route_override == "extract" and ext == ".pptx":
            raise UnsupportedFormatError("PPTX는 extract 경로를 지원하지 않습니다. route=vlm을 사용하세요.")
        return (route_override, fmt)

    if ext in EXTRACT_FORMATS:
        return ("extract", fmt)

    if ext in VLM_FORMATS:
        return ("vlm", fmt)

    # PDF auto-detection
    chars_per_mb = try_extract_pdf_text(file_bytes)
    if chars_per_mb < 100:
        return ("vlm", "pdf")
    return ("extract", "pdf")
