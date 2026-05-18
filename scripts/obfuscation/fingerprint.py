"""Per-PDF obfuscation fingerprinter.

Walks a PDF's structure (catalog, page content streams, fonts, metadata)
and emits a structured fingerprint indicating which obfuscation
techniques from the taxonomy are present.

This is a *cheap, static* pass — it does not render pages or run OCR.
Some taxonomy items (e.g. text-under-image disagreement) cannot be
resolved without rendering and are reported as ``"unknown"``; the
benchmark harness in W5 can fill those in later from rendered passes.

Usage:

    python -m scripts.obfuscation.fingerprint --pdf path/to/file.pdf
    python -m scripts.obfuscation.fingerprint \\
        --pdf-glob 'data/synthetic/**/*.pdf' \\
        --out data/obfuscation_fingerprints.jsonl
"""

from __future__ import annotations

import argparse
import dataclasses
import glob
import hashlib
import json
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import pikepdf
from pypdf import PdfReader

# PDF text-showing operators per the PDF spec (§9.4.3, Table 107)
_TEXT_SHOW_OPS = re.compile(rb"\b(?:Tj|TJ|'|\")\b")
# Rendering-mode-3 (invisible) text operator: `<mode> Tr` where mode is 3.
_TR_INVISIBLE = re.compile(rb"\b3\s+Tr\b")
# Tc operator: `<spacing> Tc` — flag values > 1.0 as suspicious.
_TC_OP = re.compile(rb"([-+]?\d+(?:\.\d+)?)\s+Tc\b")

KNOWN_BAD_PRODUCERS = (
    "MalformedScanPipeline",
    "fax-to-pdf-converter",
)

WATERMARK_KEYWORDS = (
    "CONFIDENTIAL",
    "DRAFT",
    "DO NOT DISTRIBUTE",
    "PROPRIETARY",
    "INTERNAL USE",
    "PRELIMINARY",
)

# Tc (character spacing) operand threshold. Real-world typography uses
# values up to ~2.0 for cosmetic letter-spacing on headlines and small
# caps. PDF-Poisoning-style word-scrambling uses Tc > 5. Threshold of
# 3.0 separates the two reliably in initial testing.
TC_ABUSE_THRESHOLD = 3.0


@dataclass
class Fingerprint:
    pdf_path: str
    sha256: str
    page_count: int
    pdf_producer: str | None = None
    pdf_creator: str | None = None

    # Taxonomy items (see docs/obfuscation-taxonomy.md)
    no_text_layer: bool = False  # #1
    text_layer_pages: int = 0
    image_only_pages: int = 0
    missing_tounicode_fonts: list[str] = field(default_factory=list)  # #2/#3
    has_cid_without_tounicode: bool = False  # #3
    invisible_text_pages: list[int] = field(default_factory=list)  # #4
    watermark_score: float = 0.0  # #5
    recurring_header_footer_strings: list[str] = field(default_factory=list)  # #6
    has_acroform: bool = False  # #7
    has_xfa: bool = False  # #7
    is_encrypted: bool = False  # #8
    text_image_disagreement: str = "unknown"  # #9 — requires render+OCR
    non_latin_codepoint_ratio: float = 0.0  # #10
    suspicious_tc_values: list[float] = field(default_factory=list)  # #11
    suspicious_producer: bool = False  # #12


def _sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _content_stream_bytes(page: pikepdf.Page) -> bytes:
    contents = page.obj.get("/Contents")
    if contents is None:
        return b""
    if isinstance(contents, pikepdf.Array):
        return b"".join(bytes(c.read_bytes()) for c in contents)
    return bytes(contents.read_bytes())


def _walk_fonts(pdf: pikepdf.Pdf) -> Iterable[pikepdf.Object]:
    seen = set()
    for page in pdf.pages:
        resources = page.obj.get("/Resources")
        if resources is None:
            continue
        fonts = resources.get("/Font")
        if fonts is None:
            continue
        for _name, font_obj in fonts.items():
            try:
                key = id(font_obj)
            except Exception:  # pragma: no cover - paranoia
                continue
            if key in seen:
                continue
            seen.add(key)
            yield font_obj


def _font_label(font_obj: pikepdf.Object) -> str:
    try:
        return str(font_obj.get("/BaseFont") or font_obj.get("/Name") or "<anonymous>")
    except Exception:
        return "<error>"


def _font_missing_tounicode(font_obj: pikepdf.Object) -> bool:
    if font_obj.get("/ToUnicode") is not None:
        return False
    # Base-14 PDF fonts (Helvetica, Times, Courier, etc.) have implicit
    # Unicode mappings via their standard encoding and aren't a concern.
    base = str(font_obj.get("/BaseFont") or "")
    return not any(
        name in base for name in ("Helvetica", "Times", "Courier", "Symbol", "ZapfDingbats")
    )


def _is_cid_font(font_obj: pikepdf.Object) -> bool:
    subtype = str(font_obj.get("/Subtype") or "")
    if subtype == "/Type0":
        return True
    return subtype in ("/CIDFontType0", "/CIDFontType2")


def _non_latin_ratio(text: str) -> float:
    if not text:
        return 0.0
    n_total = 0
    n_non_latin = 0
    for ch in text:
        if ch.isspace() or unicodedata.category(ch)[0] in ("P", "S", "N"):
            continue
        n_total += 1
        if ord(ch) > 0x024F:  # everything past Latin Extended-B
            n_non_latin += 1
    return n_non_latin / n_total if n_total else 0.0


def _recurring_header_footer(per_page_text: list[str], min_frac: float = 0.6) -> list[str]:
    if len(per_page_text) < 3:
        return []
    edge_lines: Counter[str] = Counter()
    for page_text in per_page_text:
        lines = [ln.strip() for ln in page_text.splitlines() if ln.strip()]
        for line in lines[:1] + lines[-1:]:
            if 3 <= len(line) <= 120:
                edge_lines[line] += 1
    threshold = int(min_frac * len(per_page_text))
    return sorted(s for s, n in edge_lines.items() if n >= threshold)


def _per_page_text(pdf_path: Path) -> list[str]:
    try:
        reader = PdfReader(str(pdf_path))
    except Exception:
        return []
    out = []
    for page in reader.pages:
        try:
            out.append(page.extract_text() or "")
        except Exception:
            out.append("")
    return out


def fingerprint_pdf(pdf_path: Path) -> Fingerprint:
    fp = Fingerprint(
        pdf_path=str(pdf_path),
        sha256=_sha256_of(pdf_path),
        page_count=0,
    )

    try:
        with pikepdf.open(pdf_path) as pdf:
            fp.page_count = len(pdf.pages)
            fp.is_encrypted = pdf.is_encrypted

            try:
                with pdf.open_metadata() as meta:
                    fp.pdf_producer = meta.get("pdf:Producer")
                    fp.pdf_creator = meta.get("xmp:CreatorTool")
            except Exception:
                docinfo = pdf.docinfo
                fp.pdf_producer = str(docinfo.get("/Producer") or "") or None
                fp.pdf_creator = str(docinfo.get("/Creator") or "") or None

            if fp.pdf_producer and any(b in fp.pdf_producer for b in KNOWN_BAD_PRODUCERS):
                fp.suspicious_producer = True
            if fp.pdf_creator and any(b in fp.pdf_creator for b in KNOWN_BAD_PRODUCERS):
                fp.suspicious_producer = True

            root = pdf.Root
            if root.get("/AcroForm") is not None:
                fp.has_acroform = True
                acroform = root["/AcroForm"]
                if acroform.get("/XFA") is not None:
                    fp.has_xfa = True

            # Per-page content-stream scan
            text_show_per_page = []
            invisible_pages = []
            tc_values: list[float] = []
            for i, page in enumerate(pdf.pages):
                content = _content_stream_bytes(page)
                shows = len(_TEXT_SHOW_OPS.findall(content))
                text_show_per_page.append(shows)
                if _TR_INVISIBLE.search(content):
                    invisible_pages.append(i)
                for m in _TC_OP.finditer(content):
                    try:
                        val = float(m.group(1))
                    except ValueError:
                        continue
                    if abs(val) > TC_ABUSE_THRESHOLD:
                        tc_values.append(val)
            fp.text_layer_pages = sum(1 for n in text_show_per_page if n > 0)
            fp.image_only_pages = sum(1 for n in text_show_per_page if n == 0)
            fp.no_text_layer = fp.text_layer_pages == 0 and fp.page_count > 0
            fp.invisible_text_pages = invisible_pages
            fp.suspicious_tc_values = sorted(set(tc_values))

            # Font scan
            for font_obj in _walk_fonts(pdf):
                if _font_missing_tounicode(font_obj):
                    fp.missing_tounicode_fonts.append(_font_label(font_obj))
                    if _is_cid_font(font_obj):
                        fp.has_cid_without_tounicode = True

            # Text-based signals (use pypdf for extraction; pikepdf's
            # page objects don't expose extract_text)
            page_text = _per_page_text(pdf_path)
            all_text = "\n".join(page_text)
            fp.non_latin_codepoint_ratio = round(_non_latin_ratio(all_text), 4)
            fp.recurring_header_footer_strings = _recurring_header_footer(page_text)

            # Watermark heuristic: two complementary signals combined.
            # (a) recurring header/footer strings with an all-caps word
            #     longer than 5 chars (works for multi-page docs).
            # (b) keyword match on any page (works on single-page docs;
            #     catches the canonical CONFIDENTIAL/DRAFT/PROPRIETARY
            #     wordmarks regulators commonly impose).
            # Score = fraction of pages exhibiting either signal.
            recurring_hits = 0
            recurring_strings = []
            for s in fp.recurring_header_footer_strings:
                if any(len(w) > 5 and w.upper() == w for w in s.split()):
                    recurring_strings.append(s)
                    recurring_hits = max(recurring_hits, sum(1 for pt in page_text if s in pt))
            keyword_hits = sum(
                1 for pt in page_text if any(kw in pt.upper() for kw in WATERMARK_KEYWORDS)
            )
            best_hits = max(recurring_hits, keyword_hits)
            fp.watermark_score = round(best_hits / max(1, fp.page_count), 3)

    except pikepdf.PasswordError:
        fp.is_encrypted = True
    except Exception as e:
        fp.pdf_producer = f"<pikepdf error: {e}>"

    return fp


def write_jsonl(fps: list[Fingerprint], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for fp in fps:
            fh.write(json.dumps(dataclasses.asdict(fp), ensure_ascii=False) + "\n")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--pdf", type=Path, help="single PDF to fingerprint")
    p.add_argument("--pdf-glob", type=str, help="glob pattern (use quotes)")
    p.add_argument("--out", type=Path, help="JSONL output path")
    args = p.parse_args()

    paths: list[Path] = []
    if args.pdf:
        paths.append(args.pdf)
    if args.pdf_glob:
        paths.extend(Path(p) for p in sorted(glob.glob(args.pdf_glob, recursive=True)))

    if not paths:
        raise SystemExit("must provide --pdf and/or --pdf-glob")

    fps = [fingerprint_pdf(p) for p in paths]

    if args.out:
        write_jsonl(fps, args.out)
        print(f"wrote {args.out} with {len(fps)} fingerprint(s)")
    else:
        for fp in fps:
            print(json.dumps(dataclasses.asdict(fp), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
