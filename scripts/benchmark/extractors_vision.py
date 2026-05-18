"""Frontier vision LLM extractors (Claude, Gemini).

Both wrappers:

1. Rasterize each page to a PNG (pypdfium2).
2. Send each page image to the provider with a fixed prompt asking for
   verbatim text.
3. Concatenate the per-page responses.

Each wrapper returns an ``ExtractionResult`` with ``error`` set when the
provider API key isn't configured, so the benchmark harness can still
run end-to-end without keys (those rows are skipped from the F1
aggregate).

Cost: 5-20 pages per source × 3 sources is ~15-60 pages per provider per
synthetic run. At current pricing that's < $1 for a synthetic-only run.

Determinism: vision models are not bit-for-bit deterministic. We use a
fixed prompt and ``temperature=0`` where supported to maximize stability
across runs, but expect 1-2pp F1 variance run-to-run.
"""

from __future__ import annotations

import base64
import io
import os
from pathlib import Path

from scripts.benchmark.base import ExtractionResult, timed

EXTRACTION_PROMPT = (
    "Transcribe the text content of this page verbatim. Preserve paragraph "
    "breaks. Do not add commentary, summaries, descriptions of the layout, "
    "or page numbers. If the page is blank, output an empty response. If "
    "the page contains an obvious watermark like 'CONFIDENTIAL' or 'DRAFT' "
    "you should still output it as part of the page text."
)


def _rasterize_pages(pdf_path: Path, dpi: int = 150) -> list[bytes]:
    try:
        import pypdfium2  # type: ignore
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("pypdfium2 required for vision extractors") from e
    doc = pypdfium2.PdfDocument(str(pdf_path))
    scale = dpi / 72.0
    images: list[bytes] = []
    try:
        for page in doc:
            pil = page.render(scale=scale).to_pil()
            buf = io.BytesIO()
            pil.save(buf, format="PNG", optimize=True)
            images.append(buf.getvalue())
    finally:
        doc.close()
    return images


class ClaudeVisionExtractor:
    name = "claude-vision"

    def __init__(self, model: str = "claude-sonnet-4-6") -> None:
        self.model = model

    def extract(self, pdf_path: Path) -> ExtractionResult:
        def _run():
            api_key = os.environ.get("ANTHROPIC_API_KEY")
            if not api_key:
                raise RuntimeError("ANTHROPIC_API_KEY not set; skipping claude-vision")
            try:
                import anthropic  # type: ignore
            except ImportError as e:  # pragma: no cover
                raise RuntimeError("anthropic SDK not installed; install [frontier] extras") from e

            client = anthropic.Anthropic(api_key=api_key)
            pages = _rasterize_pages(pdf_path)
            per_page: list[str] = []
            for page_bytes in pages:
                b64 = base64.standard_b64encode(page_bytes).decode("ascii")
                resp = client.messages.create(
                    model=self.model,
                    max_tokens=4096,
                    temperature=0,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": "image/png",
                                        "data": b64,
                                    },
                                },
                                {"type": "text", "text": EXTRACTION_PROMPT},
                            ],
                        }
                    ],
                )
                # Concatenate text blocks in the response
                page_text = "".join(block.text for block in resp.content if hasattr(block, "text"))
                per_page.append(page_text)
            return "\n".join(per_page), per_page

        return timed(self.name, pdf_path, _run)


class GeminiVisionExtractor:
    name = "gemini-vision"

    def __init__(self, model: str = "gemini-2.0-flash") -> None:
        self.model = model

    def extract(self, pdf_path: Path) -> ExtractionResult:
        def _run():
            api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
            if not api_key:
                raise RuntimeError("GOOGLE_API_KEY/GEMINI_API_KEY not set; skipping gemini-vision")
            try:
                import google.generativeai as genai  # type: ignore
            except ImportError as e:  # pragma: no cover
                raise RuntimeError(
                    "google-generativeai not installed; install [frontier] extras"
                ) from e
            from PIL import Image

            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(self.model)
            pages = _rasterize_pages(pdf_path)
            per_page: list[str] = []
            for page_bytes in pages:
                image = Image.open(io.BytesIO(page_bytes))
                resp = model.generate_content(
                    [EXTRACTION_PROMPT, image],
                    generation_config={"temperature": 0},
                )
                per_page.append((resp.text or "") if hasattr(resp, "text") else "")
            return "\n".join(per_page), per_page

        return timed(self.name, pdf_path, _run)
