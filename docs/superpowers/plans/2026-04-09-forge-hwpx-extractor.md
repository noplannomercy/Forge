# Forge HWPX Extractor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** HWPX 문서에서 텍스트+표를 추출하여 마크다운으로 변환하는 extractor 추가.

**Architecture:** `extractors/hwpx.py` 신규. ZIP → section XML → hp:t 텍스트 + hp:tbl 표 → 마크다운. router에 `.hwpx` 등록.

**Tech Stack:** Python 3.11, zipfile, xml.etree.ElementTree (표준 라이브러리만)

---

## File Map

| 파일 | 역할 | Task |
|------|------|------|
| `extractors/hwpx.py` | 신규 — HWPX 텍스트+표 추출 | 1 |
| `extractors/__init__.py` | hwpx 등록 | 2 |
| `router.py` | `.hwpx` → EXTRACT_FORMATS | 2 |
| `tests/test_extractor_hwpx.py` | 테스트 | 1 |

---

### Task 1: HWPX Extractor + 테스트

**Files:**
- Create: `extractors/hwpx.py`
- Create: `tests/test_extractor_hwpx.py`

- [ ] **Step 1: 테스트용 더미 HWPX 생성 fixture**

```python
# tests/test_extractor_hwpx.py
import io
import zipfile
import pytest
from extractors.hwpx import extract


def _make_hwpx(section_xml: str) -> bytes:
    """더미 HWPX(ZIP) 생성"""
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
    """Contents 폴더 없는 ZIP"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr("other.txt", "hello")
    result = await extract(buf.getvalue(), "bad.hwpx")
    assert result.text.strip() == ""
    assert result.quality.total_chars == 0
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/test_extractor_hwpx.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: extractors/hwpx.py 구현**

```python
# extractors/hwpx.py
import io
import os
import shutil
import tempfile
import zipfile
import xml.etree.ElementTree as ET

from models import ConvertResult, Quality

NS = {"hp": "http://www.hancom.co.kr/hwpml/2011/paragraph"}


def _table_to_md(tbl) -> str:
    """hp:tbl → markdown 표 변환"""
    rows = []
    for tr in tbl.findall(".//hp:tr", NS):
        cells = []
        for tc in tr.findall(".//hp:tc", NS):
            cell_texts = [
                t.text.strip()
                for t in tc.findall(".//hp:t", NS)
                if t.text and t.text.strip()
            ]
            cells.append(" ".join(cell_texts))
        rows.append("| " + " | ".join(cells) + " |")
    if len(rows) >= 1:
        header_sep = "| " + " | ".join(["---"] * len(rows[0].split("|")[1:-1])) + " |"
        rows.insert(1, header_sep)
    return "\n".join(rows)


def _parse_section(xml_bytes: bytes) -> tuple[list[str], list[str]]:
    """section XML에서 텍스트와 표 추출. (paragraphs, tables) 반환."""
    tree = ET.parse(io.BytesIO(xml_bytes))
    root = tree.getroot()

    parts = []
    seen_table_texts = set()

    # 표에 속한 텍스트 수집 (나중에 일반 텍스트에서 제외)
    for tbl in root.findall(".//hp:tbl", NS):
        for t in tbl.findall(".//hp:t", NS):
            if t.text and t.text.strip():
                seen_table_texts.add(id(t))
        parts.append(("table", tbl))

    # paragraph 텍스트 수집 (표 안의 텍스트 제외)
    for t_elem in root.findall(".//hp:t", NS):
        if id(t_elem) not in seen_table_texts and t_elem.text and t_elem.text.strip():
            parts.append(("text", t_elem.text.strip()))

    # 순서 재구성: root.iter()로 순서 보존
    ordered_parts = []
    table_elements = {id(tbl) for tbl in root.findall(".//hp:tbl", NS)}
    processed_tables = set()

    for elem in root.iter():
        tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag

        if tag == "tbl" and id(elem) not in processed_tables:
            processed_tables.add(id(elem))
            md_table = _table_to_md(elem)
            if md_table.strip():
                ordered_parts.append(md_table)

        elif tag == "t" and id(elem) not in seen_table_texts:
            if elem.text and elem.text.strip():
                ordered_parts.append(elem.text.strip())

    return ordered_parts


async def extract(file_bytes: bytes, file_name: str) -> ConvertResult:
    """HWPX → Markdown 변환 (텍스트 + 표)"""
    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes), 'r') as z:
            section_files = sorted([
                name for name in z.namelist()
                if name.startswith("Contents/section") and name.endswith(".xml")
            ])

            if not section_files:
                return _empty_result(file_name)

            all_parts = []
            for section_name in section_files:
                xml_bytes = z.read(section_name)
                parts = _parse_section(xml_bytes)
                all_parts.extend(parts)

    except (zipfile.BadZipFile, Exception):
        return _empty_result(file_name)

    full_text = "\n\n".join(all_parts)
    total_chars = len(full_text.strip())
    num_sections = len(section_files) if section_files else 1

    return ConvertResult(
        text=full_text,
        format="md",
        pages=num_sections,
        file_name=file_name,
        source_format="hwpx",
        route="extract",
        quality=Quality(
            total_chars=total_chars,
            chars_per_page=total_chars / num_sections if num_sections > 0 else 0,
            total_pages=num_sections,
            failed_pages=0,
            confidence="high" if total_chars > 0 else "low",
            method="extract",
        ),
    )


def _empty_result(file_name: str) -> ConvertResult:
    return ConvertResult(
        text="",
        format="md",
        pages=0,
        file_name=file_name,
        source_format="hwpx",
        route="extract",
        quality=Quality(
            total_chars=0,
            chars_per_page=0,
            total_pages=0,
            failed_pages=0,
            confidence="low",
            method="extract",
        ),
    )
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/test_extractor_hwpx.py -v`
Expected: 5 passed

- [ ] **Step 5: 커밋**

```bash
git add extractors/hwpx.py tests/test_extractor_hwpx.py
git commit -m "feat: HWPX extractor — text + table to markdown"
```

---

### Task 2: Router + Registry 등록

**Files:**
- Modify: `extractors/__init__.py`
- Modify: `router.py`
- Modify: `tests/test_router.py`

- [ ] **Step 1: 테스트 추가**

```python
# tests/test_router.py 에 추가
def test_hwpx_routes_to_extract():
    route, fmt = detect_route("문서.hwpx", b"dummy")
    assert route == "extract"
    assert fmt == "hwpx"
```

- [ ] **Step 2: router.py에 .hwpx 추가**

```python
EXTRACT_FORMATS = {".docx", ".xlsx", ".hwpx"}
```

- [ ] **Step 3: extractors/__init__.py에 hwpx 등록**

```python
from extractors.hwpx import extract as extract_hwpx

EXTRACTORS: dict[str, Callable] = {
    "docx": extract_docx,
    "xlsx": extract_xlsx,
    "hwpx": extract_hwpx,
}
```

- [ ] **Step 4: 전체 테스트**

Run: `cd C:/workspace/prj20060203/Forge && python -m pytest tests/ -v`
Expected: 전체 통과

- [ ] **Step 5: 실제 HWPX 파일로 테스트**

```bash
cd C:/workspace/prj20060203/Forge && python -c "
from extractors.hwpx import extract
import asyncio
with open('c:/workspace/prj20060203/1.제안요청서(안).hwpx', 'rb') as f:
    result = asyncio.run(extract(f.read(), '제안요청서.hwpx'))
print(f'Chars: {result.quality.total_chars}')
print(f'Pages: {result.pages}')
print(f'Tables in text: {result.text.count(\"| ---\")}')
print(f'Preview: {result.text[:200]}')
"
```

- [ ] **Step 6: 커밋**

```bash
git add extractors/__init__.py router.py tests/test_router.py
git commit -m "feat: HWPX registered in router + extractors"
```

---
