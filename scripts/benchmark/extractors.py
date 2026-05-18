"""First three extractor wrappers for W5.

Two run on the core deps (pypdf, pdfplumber is optional). One shells out
to ``pdftotext`` (poppler) and skips gracefully if the binary is absent.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from scripts.benchmark.base import ExtractionResult, timed


class PypdfExtractor:
    name = "pypdf"

    def extract(self, pdf_path: Path) -> ExtractionResult:
        def _run():
            from pypdf import PdfReader

            reader = PdfReader(str(pdf_path))
            per_page = [p.extract_text() or "" for p in reader.pages]
            return "\n".join(per_page), per_page

        return timed(self.name, pdf_path, _run)


class PdfplumberExtractor:
    name = "pdfplumber"

    def extract(self, pdf_path: Path) -> ExtractionResult:
        def _run():
            try:
                import pdfplumber  # type: ignore
            except ImportError as e:  # pragma: no cover - benchmark extras
                raise RuntimeError(
                    "pdfplumber not installed; install [benchmark] extras"
                ) from e
            with pdfplumber.open(pdf_path) as pdf:
                per_page = [p.extract_text() or "" for p in pdf.pages]
            return "\n".join(per_page), per_page

        return timed(self.name, pdf_path, _run)


class PdftotextSubprocExtractor:
    """Wraps the poppler ``pdftotext`` CLI. Falls through with an error
    result if the binary isn't on PATH."""

    name = "pdftotext"

    def extract(self, pdf_path: Path) -> ExtractionResult:
        def _run():
            binary = shutil.which("pdftotext")
            if not binary:
                raise RuntimeError("pdftotext binary not on PATH")
            proc = subprocess.run(
                [binary, "-layout", "-enc", "UTF-8", str(pdf_path), "-"],
                capture_output=True,
                check=True,
                text=True,
                timeout=120,
            )
            text = proc.stdout
            # pdftotext separates pages with form-feed (U+000C)
            per_page = text.split("\x0c")
            return text, per_page

        return timed(self.name, pdf_path, _run)


def default_extractors() -> list:
    from scripts.benchmark.extractors_advanced import (
        DoclingExtractor,
        PATCascadeExtractor,
    )
    from scripts.benchmark.extractors_ocr import TesseractOCRExtractor
    from scripts.benchmark.extractors_vision import (
        ClaudeVisionExtractor,
        GeminiVisionExtractor,
    )

    return [
        PypdfExtractor(),
        PdfplumberExtractor(),
        PdftotextSubprocExtractor(),
        TesseractOCRExtractor(),
        DoclingExtractor(),
        ClaudeVisionExtractor(),
        GeminiVisionExtractor(),
        PATCascadeExtractor(),
    ]
