import io
import zipfile
import pytest
from extractors.hwpx import extract


def _make_hwpx(section_xml: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr("Contents/section0.xml", section_xml)
    return buf.getvalue()


SAMPLE_XML = '''<?xml version="1.0" encoding="UTF-8"?>
<sec xmlns="http://www.hancom.co.kr/hwpml/2011/section"
     xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">
  <hp:p>
    <hp:run><hp:t>제목입니다</hp:t></hp:run>
  </hp:p>
  <hp:p>
    <hp:run><hp:t>본문 텍스트입니다.</hp:t></hp:run>
  </hp:p>
  <hp:tbl>
    <hp:tr>
      <hp:tc><hp:p><hp:run><hp:t>이름</hp:t></hp:run></hp:p></hp:tc>
      <hp:tc><hp:p><hp:run><hp:t>나이</hp:t></hp:run></hp:p></hp:tc>
    </hp:tr>
    <hp:tr>
      <hp:tc><hp:p><hp:run><hp:t>홍길동</hp:t></hp:run></hp:p></hp:tc>
      <hp:tc><hp:p><hp:run><hp:t>30</hp:t></hp:run></hp:p></hp:tc>
    </hp:tr>
  </hp:tbl>
  <hp:p>
    <hp:run><hp:t>끝.</hp:t></hp:run>
  </hp:p>
</sec>'''


EMPTY_XML = '''<?xml version="1.0" encoding="UTF-8"?>
<sec xmlns="http://www.hancom.co.kr/hwpml/2011/section"
     xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">
</sec>'''


@pytest.mark.asyncio
async def test_hwpx_extracts_text():
    hwpx = _make_hwpx(SAMPLE_XML)
    result = await extract(hwpx, "test.hwpx")
    assert "제목입니다" in result.text
    assert "본문 텍스트입니다" in result.text
    assert "끝" in result.text


@pytest.mark.asyncio
async def test_hwpx_extracts_table():
    hwpx = _make_hwpx(SAMPLE_XML)
    result = await extract(hwpx, "test.hwpx")
    assert "이름" in result.text
    assert "홍길동" in result.text
    assert "|" in result.text


@pytest.mark.asyncio
async def test_hwpx_result_metadata():
    hwpx = _make_hwpx(SAMPLE_XML)
    result = await extract(hwpx, "test.hwpx")
    assert result.source_format == "hwpx"
    assert result.route == "extract"
    assert result.format == "md"
    assert result.quality.confidence == "high"
    assert result.quality.total_chars > 0


@pytest.mark.asyncio
async def test_hwpx_empty():
    hwpx = _make_hwpx(EMPTY_XML)
    result = await extract(hwpx, "empty.hwpx")
    assert result.text.strip() == ""
    assert result.quality.total_chars == 0


@pytest.mark.asyncio
async def test_hwpx_no_contents_dir():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr("other.txt", "hello")
    result = await extract(buf.getvalue(), "bad.hwpx")
    assert result.text.strip() == ""
    assert result.quality.total_chars == 0
