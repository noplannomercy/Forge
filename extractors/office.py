import asyncio
import os
import shutil
import sys
import tempfile


def _find_soffice() -> str:
    """soffice 실행 파일 경로 탐색"""
    if shutil.which("soffice"):
        return "soffice"
    # Windows 기본 설치 경로
    if sys.platform == "win32":
        for path in [
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        ]:
            if os.path.isfile(path):
                return path
    raise FileNotFoundError("LibreOffice(soffice) not found. Install LibreOffice.")


async def _read_and_cleanup(pdf_path: str, tmpdir: str) -> bytes:
    """PDF 파일 읽고 임시 디렉토리 정리"""
    try:
        with open(pdf_path, "rb") as f:
            return f.read()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


async def pptx_to_pdf(file_bytes: bytes) -> bytes:
    """PPTX → PDF 변환 (LibreOffice headless)"""
    tmpdir = tempfile.mkdtemp()
    input_path = os.path.join(tmpdir, "input.pptx")

    with open(input_path, "wb") as f:
        f.write(file_bytes)

    soffice = _find_soffice()
    process = await asyncio.create_subprocess_exec(
        soffice, "--headless", "--convert-to", "pdf",
        "--outdir", tmpdir, input_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()

    if process.returncode != 0:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise RuntimeError(f"LibreOffice conversion failed: {stderr.decode()}")

    pdf_path = os.path.join(tmpdir, "input.pdf")
    return await _read_and_cleanup(pdf_path, tmpdir)


async def convert_hwpx_to_docx(file_bytes: bytes) -> bytes:
    """HWPX → DOCX 변환 (LibreOffice headless).

    T15: docling-serve는 HWPX를 네이티브로 파싱하지 못하므로, docling 경로에서
    HWPX를 처리하려면 먼저 DOCX로 변환해야 한다. LibreOffice가 HWPX 입력을
    인식하려면 대응 import 필터가 설치되어 있어야 한다(일반적으로 `libreoffice-core`
    + H/Korean filter 번들). 실패 시 RuntimeError를 raise하여 상위 레이어에서
    fallback(extract route) 결정을 내리도록 한다.
    """
    tmpdir = tempfile.mkdtemp()
    input_path = os.path.join(tmpdir, "input.hwpx")

    with open(input_path, "wb") as f:
        f.write(file_bytes)

    soffice = _find_soffice()
    process = await asyncio.create_subprocess_exec(
        soffice, "--headless", "--convert-to", "docx",
        "--outdir", tmpdir, input_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()

    if process.returncode != 0:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise RuntimeError(f"LibreOffice HWPX→DOCX failed: {stderr.decode()}")

    docx_path = os.path.join(tmpdir, "input.docx")
    if not os.path.exists(docx_path):
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise RuntimeError(
            f"LibreOffice HWPX→DOCX failed: output not produced. stdout={stdout.decode()!r}"
        )

    try:
        with open(docx_path, "rb") as f:
            return f.read()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
