import pytest
from extractors.xlsx import extract


@pytest.mark.asyncio
async def test_xlsx_extracts_sheet_names(sample_xlsx_bytes):
    result = await extract(sample_xlsx_bytes, "test.xlsx")
    assert "매출" in result.text
    assert "비용" in result.text


@pytest.mark.asyncio
async def test_xlsx_extracts_data_as_table(sample_xlsx_bytes):
    result = await extract(sample_xlsx_bytes, "test.xlsx")
    assert "월" in result.text
    assert "1000" in result.text
    assert "|" in result.text  # markdown 표 형식


@pytest.mark.asyncio
async def test_xlsx_multiple_sheets(sample_xlsx_bytes):
    result = await extract(sample_xlsx_bytes, "test.xlsx")
    assert "인건비" in result.text
    assert "500" in result.text


@pytest.mark.asyncio
async def test_xlsx_result_metadata(sample_xlsx_bytes):
    result = await extract(sample_xlsx_bytes, "test.xlsx")
    assert result.source_format == "xlsx"
    assert result.route == "extract"
    assert result.pages == 2  # 시트 2개
    assert result.quality.confidence == "high"
