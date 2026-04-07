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
