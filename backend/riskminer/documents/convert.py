"""Office -> PDF with LibreOffice headless (MPL-2.0, separate binary; api_contract §4). Owner: S0.

One soffice process per call with its own throwaway profile (`-env:UserInstallation`), so parallel calls never hit the
profile lock. Used by the upload (DOCX/DOC/ODT -> PDF for page text) and by the analysis pack (`analysis/pack.py`, B):

    from riskminer.documents.convert import to_pdf, ConvertError
    pdf_path = to_pdf(docx_path, out_dir)          # blocking: wrap in asyncio.to_thread in request paths
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

DEFAULT_TIMEOUT_S = 60


class ConvertError(RuntimeError):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code, self.detail = code, detail


def soffice() -> str | None:
    return shutil.which("soffice") or shutil.which("libreoffice")


def to_pdf(src: Path, outdir: Path, timeout: int = DEFAULT_TIMEOUT_S) -> Path:
    """-> outdir/<src.stem>.pdf. Raises ConvertError(converter_unavailable | convert_timeout | convert_failed)."""
    exe = soffice()
    if not exe:
        raise ConvertError("converter_unavailable", "LibreOffice (soffice) is not installed")
    outdir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="lo_") as prof:
        try:
            r = subprocess.run([exe, f"-env:UserInstallation=file://{prof}/{uuid.uuid4().hex}", "--headless", "--norestore",
                                "--nolockcheck", "--convert-to", "pdf", "--outdir", str(outdir), str(src)],
                               capture_output=True, timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            raise ConvertError("convert_timeout", f"soffice exceeded {timeout} s") from None
    out = outdir / (src.stem + ".pdf")
    if not out.exists() or out.stat().st_size == 0:
        raise ConvertError("convert_failed", (r.stderr or b"").decode("utf-8", "replace")[-300:] or "no output")
    return out
