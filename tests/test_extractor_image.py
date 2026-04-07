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
