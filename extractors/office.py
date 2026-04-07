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
