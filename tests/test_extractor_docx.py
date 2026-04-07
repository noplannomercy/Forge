import pytest
from extractors.docx import extract


@pytest.mark.asyncio
async def test_docx_extracts_heading(sample_docx_bytes):
    result = await extract(sample_docx_bytes, "test.docx")
    assert "# 제목" in result.text


@pytest.mark.asyncio
async def test_docx_extracts_paragraph(sample_docx_bytes):
    result = await extract(sample_docx_bytes, "test.docx")
    assert "본문 텍스트입니다" in result.text


@pytest.mark.asyncio
async def test_docx_extracts_table(sample_docx_bytes):
    result = await extract(sample_docx_bytes, "test.docx")
    assert "이름" in result.text
    assert "홍길동" in result.text
    assert "|" in result.text  # markdown 표 형식


@pytest.mark.asyncio
async def test_docx_result_metadata(sample_docx_bytes):
    result = await extract(sample_docx_bytes, "test.docx")
    assert result.source_format == "docx"
    assert result.route == "extract"
    assert result.format == "md"
    assert result.quality.confidence == "high"
    assert result.quality.total_chars > 0


@pytest.mark.asyncio
async def test_empty_docx(empty_docx_bytes):
    result = await extract(empty_docx_bytes, "empty.docx")
    assert result.text == "" or result.text.strip() == ""
    assert result.quality.total_chars == 0
