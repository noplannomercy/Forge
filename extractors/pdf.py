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
