"""OCR-based extractor (rasterize + Tesseract).

This is the only extractor in the bench that recovers text from a
rasterized PDF — the rest hinge on a text layer being present.

Operates in two stages:

1. Rasterize each page to a PIL Image via pypdfium2 at ``dpi`` resolution.
2. Run ``pytesseract.image_to_string`` per page; concatenate results.

Skips gracefully (returns an ``ExtractionResult`` with ``error`` set) if
the ``tesseract`` binary isn't installed, or pypdfium2/pytesseract
aren't importable.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from pdf_plaintext_extraction.benchmark.base import ExtractionResult, timed


class TesseractOCRExtractor:
    name = "tesseract"

    def __init__(self, dpi: int = 200) -> None:
        self.dpi = dpi

    def extract(self, pdf_path: Path) -> ExtractionResult:
        def _run():
            if not shutil.which("tesseract"):
                raise RuntimeError("tesseract binary not on PATH")
            try:
                import pypdfium2  # type: ignore
                import pytesseract  # type: ignore
            except ImportError as e:  # pragma: no cover - benchmark extras
                raise RuntimeError(
                    "pypdfium2 + pytesseract required; install [benchmark] extras"
                ) from e

            doc = pypdfium2.PdfDocument(str(pdf_path))
            scale = self.dpi / 72.0
            per_page: list[str] = []
            try:
                for page in doc:
                    image = page.render(scale=scale).to_pil()
                    per_page.append(pytesseract.image_to_string(image) or "")
            finally:
                doc.close()
            return "\n".join(per_page), per_page

        return timed(self.name, pdf_path, _run)
