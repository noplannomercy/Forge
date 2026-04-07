from extractors.docx import extract as extract_docx
from extractors.pptx import extract as extract_pptx
from extractors.xlsx import extract as extract_xlsx

EXTRACTORS: dict[str, callable] = {
    "docx": extract_docx,
    "pptx": extract_pptx,
    "xlsx": extract_xlsx,
}
