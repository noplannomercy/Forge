import io
import zipfile
import xml.etree.ElementTree as ET

from models import ConvertResult, Quality

NS = {"hp": "http://www.hancom.co.kr/hwpml/2011/paragraph"}


def _table_to_md(tbl) -> str:
    """hp:tbl → markdown 표"""
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
        num_cols = len(rows[0].split("|")) - 2
        header_sep = "| " + " | ".join(["---"] * num_cols) + " |"
        rows.insert(1, header_sep)
    return "\n".join(rows)


def _parse_section(xml_bytes: bytes) -> list[str]:
    """section XML에서 텍스트와 표 추출. 순서 보존."""
    tree = ET.parse(io.BytesIO(xml_bytes))
    root = tree.getroot()

    # 표에 속한 hp:t element id 수집
    table_text_ids = set()
    for tbl in root.findall(".//hp:tbl", NS):
        for t in tbl.findall(".//hp:t", NS):
            table_text_ids.add(id(t))

    # root.iter()로 순서 보존하며 텍스트/표 추출
    ordered_parts = []
    processed_tables = set()

    for elem in root.iter():
        tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag

        if tag == "tbl" and id(elem) not in processed_tables:
            processed_tables.add(id(elem))
            md_table = _table_to_md(elem)
            if md_table.strip():
                ordered_parts.append(md_table)

        elif tag == "t" and id(elem) not in table_text_ids:
            if elem.text and elem.text.strip():
                ordered_parts.append(elem.text.strip())

    return ordered_parts


async def extract(file_bytes: bytes, file_name: str) -> ConvertResult:
    """HWPX → Markdown 변환 (텍스트 + 표)"""
    section_files = []
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
