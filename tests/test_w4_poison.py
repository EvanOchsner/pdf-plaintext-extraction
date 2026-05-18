"""Verify W4 poisoning techniques produce the expected obfuscation signal."""

from __future__ import annotations

from pathlib import Path

import pytest
from pypdf import PdfReader

from pdf_plaintext_extraction._paths import package_sources_dir
from pdf_plaintext_extraction.synthesize import poison
from pdf_plaintext_extraction.synthesize.clean_pdf import render

SOURCES_DIR = package_sources_dir()


@pytest.fixture
def source_and_clean(tmp_path: Path) -> tuple[Path, Path]:
    sources = sorted(SOURCES_DIR.glob("*.txt"))
    if not sources:
        pytest.skip("seed corpus not fetched")
    out = tmp_path / "clean.pdf"
    render(sources[0], out)
    return sources[0], out


def test_watermark_leaks_into_extracted_text(
    source_and_clean: tuple[Path, Path], tmp_path: Path
) -> None:
    src, clean_pdf = source_and_clean
    out = tmp_path / "watermarked.pdf"
    poison.poison_watermark(src, clean_pdf, out)
    text = "\n".join(p.extract_text() for p in PdfReader(str(out)).pages)
    assert "CONFIDENTIAL" in text, "watermark should appear in extractable text layer"


def test_metadata_swap_overwrites_producer(
    source_and_clean: tuple[Path, Path], tmp_path: Path
) -> None:
    src, clean_pdf = source_and_clean
    out = tmp_path / "swapped.pdf"
    poison.poison_metadata_swap(src, clean_pdf, out)
    meta = PdfReader(str(out)).metadata
    assert meta is not None
    assert meta.get("/Producer") == "MalformedScanPipeline 0.1"
    assert meta.get("/Creator") == "fax-to-pdf-converter"


def test_invisible_text_payload_appears_in_extracted_text(
    source_and_clean: tuple[Path, Path], tmp_path: Path
) -> None:
    src, clean = source_and_clean
    out = tmp_path / "invisible.pdf"
    poison.poison_invisible_text(src, clean, out)
    text = "\n".join(p.extract_text() for p in PdfReader(str(out)).pages)
    assert "INVISIBLE_PAYLOAD" in text or "ignore previous instructions" in text


def test_char_spacing_injects_tc_into_content_stream(
    source_and_clean: tuple[Path, Path], tmp_path: Path
) -> None:
    """Whether a given extractor is fooled by abnormal Tc is the
    benchmark question — not a precondition. Here we only assert the
    technique writes a poisoned-shaped content stream."""
    import re

    import pikepdf

    src, clean = source_and_clean
    out = tmp_path / "spaced.pdf"
    poison.poison_char_spacing(src, clean, out)
    with pikepdf.open(out) as pdf:
        stream = bytes(pdf.pages[0].obj.get("/Contents").read_bytes())
    tc_values = [float(m.group(1)) for m in re.finditer(rb"([-+]?\d+(?:\.\d+)?)\s+Tc\b", stream)]
    assert tc_values, "char_spacing must emit at least one Tc operator"
    assert max(tc_values) >= 3.0, "Tc value must exceed the abuse threshold"


def test_homoglyph_substitutes_at_least_a_few_letters(
    source_and_clean: tuple[Path, Path], tmp_path: Path
) -> None:
    src, clean = source_and_clean
    out = tmp_path / "homo.pdf"
    poison.poison_homoglyph(src, clean, out)
    text = "\n".join(p.extract_text() for p in PdfReader(str(out)).pages)
    # At least one Cyrillic codepoint should be present in the extracted text
    assert any(0x0400 <= ord(c) <= 0x04FF for c in text), (
        "homoglyph poisoning should introduce Cyrillic codepoints"
    )


def test_rasterize_strips_text_layer(source_and_clean: tuple[Path, Path], tmp_path: Path) -> None:
    src, clean = source_and_clean
    out = tmp_path / "raster.pdf"
    poison.poison_rasterize(src, clean, out)
    text = "\n".join(p.extract_text() for p in PdfReader(str(out)).pages)
    # Rasterizing should leave the PDF with no text layer at all
    assert text.strip() == "", "rasterized PDF should have no extractable text"
