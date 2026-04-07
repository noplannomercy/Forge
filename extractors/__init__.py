from collections.abc import Callable

from extractors.docx import extract as extract_docx
from extractors.xlsx import extract as extract_xlsx

EXTRACTORS: dict[str, Callable] = {
    "docx": extract_docx,
    "xlsx": extract_xlsx,
}
