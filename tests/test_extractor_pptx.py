import pytest
from extractors.pptx import extract


@pytest.mark.asyncio
async def test_pptx_extracts_slide_titles(sample_pptx_bytes):
    result = await extract(sample_pptx_bytes, "test.pptx")
    assert "슬라이드 1 제목" in result.text
    assert "슬라이드 2 제목" in result.text


@pytest.mark.asyncio
async def test_pptx_extracts_slide_body(sample_pptx_bytes):
    result = await extract(sample_pptx_bytes, "test.pptx")
    assert "슬라이드 1 본문" in result.text
    assert "슬라이드 2 본문" in result.text


@pytest.mark.asyncio
async def test_pptx_slide_numbering(sample_pptx_bytes):
    result = await extract(sample_pptx_bytes, "test.pptx")
    assert "## 슬라이드 1" in result.text
    assert "## 슬라이드 2" in result.text


@pytest.mark.asyncio
async def test_pptx_result_metadata(sample_pptx_bytes):
    result = await extract(sample_pptx_bytes, "test.pptx")
    assert result.source_format == "pptx"
    assert result.route == "extract"
    assert result.pages == 2
    assert result.quality.total_pages == 2
    assert result.quality.confidence == "high"
