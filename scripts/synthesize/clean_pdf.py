"""Render a plain-text source into a deterministic clean PDF.

The output PDF is the "control" form of the synthetic benchmark: it
should be trivially extractable by any text-layer reader (pdftotext,
pypdf, pdfplumber) with near-zero error. Any extractor that fails on
the clean output has a harness bug, not a poisoning effect.

Determinism: reportlab's ``Canvas(invariant=1)`` zeros the document
ID and producer-creation timestamps, so re-rendering the same source
yields a byte-identical PDF.

Usage:

    python -m scripts.synthesize.clean_pdf \\
        --source data/synthetic/sources/example.txt \\
        --out data/synthetic/clean/example.pdf
"""

from __future__ import annotations

import argparse
import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph

LEFT_MARGIN = 72.0
RIGHT_MARGIN = 72.0
TOP_MARGIN = 72.0
BOTTOM_MARGIN = 72.0
LINE_HEIGHT = 14.0


@dataclass(frozen=True)
class RenderOptions:
    """Tunables exposed to the synthesize pipeline.

    The default values reproduce the clean-baseline appearance. Poisoning
    techniques flip the relevant knob and otherwise inherit the defaults.
    """

    font_name: str = "Helvetica"
    font_size: float = 11.0
    char_space: float = 0.0  # PDF Tc operator; abnormal values >3.0
    text_render_mode: int = 0  # 0 = fill (visible), 3 = invisible
    extra_invisible_overlay: str = ""  # adds an off-content invisible text payload
    page_size: tuple[float, float] = field(default=LETTER)


def _body_style(opts: RenderOptions) -> ParagraphStyle:
    return ParagraphStyle(
        name="body",
        fontName=opts.font_name,
        fontSize=opts.font_size,
        leading=LINE_HEIGHT,
        spaceAfter=8,
    )


@dataclass(frozen=True)
class RenderResult:
    out_path: Path
    page_count: int
    sha256: str


def _paragraphs(text: str) -> list[str]:
    blocks = []
    current: list[str] = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line:
            if current:
                blocks.append(" ".join(current))
                current = []
            continue
        current.append(line)
    if current:
        blocks.append(" ".join(current))
    return blocks


def render(
    source: Path,
    out: Path,
    *,
    title: str | None = None,
    options: RenderOptions | None = None,
) -> RenderResult:
    opts = options or RenderOptions()
    text = source.read_text(encoding="utf-8")
    paragraphs = _paragraphs(text)
    if not paragraphs:
        raise ValueError(f"source has no text content: {source}")

    out.parent.mkdir(parents=True, exist_ok=True)

    page_width, page_height = opts.page_size
    body_width = page_width - LEFT_MARGIN - RIGHT_MARGIN
    body_style = _body_style(opts)

    canvas = Canvas(
        str(out),
        pagesize=opts.page_size,
        invariant=1,
        pageCompression=0,
    )
    canvas.setTitle(title or source.stem)
    canvas.setAuthor("pdf-plaintext-extraction synthetic gold set")
    canvas.setSubject("control PDF for extraction benchmark")
    canvas.setCreator("pdf-plaintext-extraction/clean_pdf.py")
    canvas.setProducer("pdf-plaintext-extraction/clean_pdf.py")

    # ``char_space`` is applied post-render by injecting `<v> Tc` into
    # each text block — reportlab's Paragraph emits its own state so
    # setting Tc on the canvas pre-draw has no effect. See
    # scripts/synthesize/poison.py::poison_char_spacing.

    y_cursor = page_height - TOP_MARGIN
    page_count = 1

    for block in paragraphs:
        para = Paragraph(_escape_xml(block), body_style)
        used_w, used_h = para.wrap(body_width, y_cursor - BOTTOM_MARGIN)
        if used_h > y_cursor - BOTTOM_MARGIN:
            canvas.showPage()
            page_count += 1
            y_cursor = page_height - TOP_MARGIN
            used_w, used_h = para.wrap(body_width, y_cursor - BOTTOM_MARGIN)
        para.drawOn(canvas, LEFT_MARGIN, y_cursor - used_h)
        y_cursor -= used_h + body_style.spaceAfter

    if opts.extra_invisible_overlay:
        # Render mode 3 = "neither fill nor stroke" — text exists in the
        # content stream but is not visually rendered. We use a fresh
        # TextObject so the render mode is scoped to the payload only.
        text_obj = canvas.beginText(LEFT_MARGIN, BOTTOM_MARGIN / 2.0)
        text_obj.setFont(opts.font_name, opts.font_size)
        text_obj.setTextRenderMode(3)
        text_obj.textOut(opts.extra_invisible_overlay)
        canvas.drawText(text_obj)

    canvas.save()

    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    return RenderResult(out_path=out, page_count=page_count, sha256=digest)


def _escape_xml(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--title", type=str, default=None)
    args = p.parse_args()

    result = render(args.source, args.out, title=args.title)
    print(f"wrote {result.out_path}  pages={result.page_count}  sha256={result.sha256[:16]}…")


if __name__ == "__main__":
    main()
