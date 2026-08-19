"""Local PDF inspection and page rendering through Poppler."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path


class RenderError(RuntimeError):
    """Raised when a PDF cannot be inspected or rendered."""


def validate_pdf(path: Path) -> Path:
    """Resolve and validate a PDF input without modifying it."""

    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise RenderError(f"PDF does not exist: {resolved}")
    if resolved.suffix.lower() != ".pdf":
        raise RenderError(f"Expected a .pdf input: {resolved}")
    return resolved


class PdfRenderer:
    """Render one page at a time so page work can be retried independently."""

    def __init__(self, *, dpi: int = 200) -> None:
        if dpi < 72 or dpi > 600:
            raise ValueError("render DPI must be between 72 and 600")
        self.dpi = dpi
        self._pdfinfo = shutil.which("pdfinfo")
        self._pdftoppm = shutil.which("pdftoppm")

    def page_count(self, pdf_path: Path) -> int:
        """Read the page count using pdfinfo, with pypdf as a fallback."""

        pdf_path = validate_pdf(pdf_path)
        if self._pdfinfo:
            result = subprocess.run(
                [self._pdfinfo, str(pdf_path)],
                capture_output=True,
                text=True,
                check=False,
            )
            match = re.search(r"^Pages:\s*(\d+)\s*$", result.stdout, flags=re.MULTILINE)
            if match:
                return int(match.group(1))

        try:
            from pypdf import PdfReader

            return len(PdfReader(str(pdf_path), strict=False).pages)
        except Exception as exc:
            tool_note = "pdfinfo is unavailable or did not report Pages. "
            raise RenderError(f"{tool_note}Install Poppler or pypdf to inspect {pdf_path}: {exc}") from exc

    def render_page(self, pdf_path: Path, page_number: int, output_dir: Path) -> Path:
        """Render a one-based PDF page to a PNG and validate the result."""

        pdf_path = validate_pdf(pdf_path)
        if not self._pdftoppm:
            raise RenderError("pdftoppm was not found. Install Poppler before running Vertex OCR.")
        if page_number < 1:
            raise ValueError("page number must be one-based")

        output_dir.mkdir(parents=True, exist_ok=True)
        prefix = output_dir / f"page-{page_number:04d}"
        image_path = prefix.with_suffix(".png")
        image_path.unlink(missing_ok=True)
        result = subprocess.run(
            [
                self._pdftoppm,
                "-png",
                "-r",
                str(self.dpi),
                "-f",
                str(page_number),
                "-l",
                str(page_number),
                "-singlefile",
                str(pdf_path),
                str(prefix),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0 or not image_path.is_file():
            detail = result.stderr.strip() or result.stdout.strip() or "no renderer output"
            raise RenderError(f"Could not render PDF page {page_number}: {detail}")
        if image_path.stat().st_size < 32 or image_path.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
            raise RenderError(f"Rendered page {page_number} is not a valid PNG")
        return image_path

