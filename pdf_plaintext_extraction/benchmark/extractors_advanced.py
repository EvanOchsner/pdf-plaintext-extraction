"""Two more extractors: Docling (IBM) and the PAT cascade (sibling repo).

Both gracefully error if their requirements aren't met:

- ``Docling`` doesn't yet support Python 3.13. On 3.13 we skip with an
  informative error row.
- ``PAT cascade`` imports from a sibling-repo path. If
  ``PERSONAL_ADVOCACY_TOOLKIT_PATH`` env var points to the PAT repo
  (or the default ``../personal-advocacy-toolkit`` exists), we add it
  to ``sys.path`` and import. Otherwise we error gracefully.
"""

from __future__ import annotations

import os
from pathlib import Path

from pdf_plaintext_extraction.benchmark.base import ExtractionResult, timed

ROOT = Path(__file__).resolve().parents[2]


class DoclingExtractor:
    name = "docling"

    def extract(self, pdf_path: Path) -> ExtractionResult:
        def _run():
            try:
                from docling.document_converter import DocumentConverter  # type: ignore
            except ImportError as e:
                raise RuntimeError("docling not installed; run 'uv sync --extra benchmark'") from e
            converter = DocumentConverter()
            result = converter.convert(str(pdf_path))
            text = result.document.export_to_markdown()
            # Docling returns a document object; we treat per-page as
            # unavailable and put everything in a single-element list.
            return text, [text]

        return timed(self.name, pdf_path, _run)


class PATCascadeExtractor:
    name = "pat-cascade"

    def __init__(self, pat_repo: Path | None = None) -> None:
        if pat_repo is None:
            pat_repo = self._discover_pat_repo()
        self.pat_repo = pat_repo

    @staticmethod
    def _discover_pat_repo() -> Path | None:
        env = os.environ.get("PERSONAL_ADVOCACY_TOOLKIT_PATH")
        if env:
            return Path(env)
        sibling = ROOT.parent / "personal-advocacy-toolkit"
        if (sibling / "scripts" / "extraction" / "cascade.py").exists():
            return sibling
        return None

    # Subprocess-invoked because PAT and pdf-plaintext-extraction both
    # ship a top-level ``scripts`` package — in-process import would
    # collide.
    # We run PAT's cascade in its own venv via a small inline script and
    # round-trip the result as JSON.
    _INLINE_SCRIPT = """
import json, sys
from pathlib import Path
from scripts.extraction.cascade import extract
result = extract(
    Path(sys.argv[1]),
    interactive=False,
    verbose=False,
    vlm_provider="tesseract",
)
per_page = [p.text for p in result.page_results] if result.page_results else [result.text]
sys.stdout.write(json.dumps({
    "text": result.text,
    "per_page": per_page,
    "method": result.method,
    "tier": result.tier,
}))
"""

    def extract(self, pdf_path: Path) -> ExtractionResult:
        def _run():
            import json
            import subprocess

            if not self.pat_repo:
                raise RuntimeError(
                    "PAT repo not found; set PERSONAL_ADVOCACY_TOOLKIT_PATH "
                    "or place pdf-plaintext-extraction next to personal-advocacy-toolkit"
                )
            pat_python = self.pat_repo / ".venv" / "bin" / "python"
            if not pat_python.exists():
                raise RuntimeError(
                    f"PAT venv not found at {pat_python}; run 'uv sync' in the PAT repo"
                )
            proc = subprocess.run(
                [str(pat_python), "-c", self._INLINE_SCRIPT, str(pdf_path.resolve())],
                cwd=self.pat_repo,
                capture_output=True,
                text=True,
                timeout=300,
            )
            if proc.returncode != 0:
                raise RuntimeError(
                    f"PAT cascade exited {proc.returncode}: {proc.stderr.strip()[-400:]}"
                )
            payload = json.loads(proc.stdout)
            return payload["text"], payload.get("per_page") or []

        return timed(self.name, pdf_path, _run)
