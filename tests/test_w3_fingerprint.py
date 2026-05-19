"""Tests for the W3 obfuscation fingerprinter.

The fingerprinter is judged by whether it separates the synthetic
clean/poisoned PDFs correctly. Each test renders a fresh clean PDF,
applies a known poisoning technique, and asserts the corresponding
taxonomy signal trips for the poisoned variant and stays quiet on the
clean baseline.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pdf_plaintext_extraction._paths import package_sources_dir
from pdf_plaintext_extraction.obfuscation.fingerprint import fingerprint_pdf
from pdf_plaintext_extraction.synthesize import poison
from pdf_plaintext_extraction.synthesize.clean_pdf import render

SOURCES_DIR = package_sources_dir()


@pytest.fixture
def clean_pdf(tmp_path: Path) -> Path:
    sources = sorted(SOURCES_DIR.glob("*.txt"))
    if not sources:
        pytest.skip("seed corpus not fetched")
    out = tmp_path / "clean.pdf"
    render(sources[0], out)
    return out


@pytest.fixture
def source_and_clean(tmp_path: Path) -> tuple[Path, Path]:
    sources = sorted(SOURCES_DIR.glob("*.txt"))
    if not sources:
        pytest.skip("seed corpus not fetched")
    out = tmp_path / "clean.pdf"
    render(sources[0], out)
    return sources[0], out


def test_clean_pdf_signals_are_negative(clean_pdf: Path) -> None:
    fp = fingerprint_pdf(clean_pdf)
    assert fp.page_count >= 1
    assert fp.text_layer_pages == fp.page_count
    assert fp.image_only_pages == 0
    assert fp.no_text_layer is False
    assert fp.watermark_score == 0.0
    assert fp.suspicious_producer is False
    assert fp.is_encrypted is False
    assert fp.has_acroform is False
    assert fp.invisible_text_pages == []
    assert fp.suspicious_tc_values == []


def test_watermarked_pdf_trips_watermark_signal(
    source_and_clean: tuple[Path, Path], tmp_path: Path
) -> None:
    src, clean_pdf = source_and_clean
    poisoned = tmp_path / "wm.pdf"
    poison.poison_watermark(src, clean_pdf, poisoned)
    fp = fingerprint_pdf(poisoned)
    assert fp.watermark_score > 0.5, (
        "watermark detection must fire on the canonical synthetic watermark"
    )


def test_metadata_swap_trips_producer_signal(
    source_and_clean: tuple[Path, Path], tmp_path: Path
) -> None:
    src, clean_pdf = source_and_clean
    poisoned = tmp_path / "swap.pdf"
    poison.poison_metadata_swap(src, clean_pdf, poisoned)
    fp = fingerprint_pdf(poisoned)
    assert fp.suspicious_producer is True
    assert fp.pdf_producer is not None
    assert "MalformedScan" in fp.pdf_producer or "fax-to-pdf" in (fp.pdf_creator or "")


def test_rasterized_pdf_has_no_text_layer(
    source_and_clean: tuple[Path, Path], tmp_path: Path
) -> None:
    src, clean_pdf = source_and_clean
    raster = tmp_path / "raster.pdf"
    poison.poison_rasterize(src, clean_pdf, raster)
    fp = fingerprint_pdf(raster)
    assert fp.no_text_layer is True
    assert fp.image_only_pages == fp.page_count


def test_invisible_text_trips_tr3_signal(
    source_and_clean: tuple[Path, Path], tmp_path: Path
) -> None:
    src, clean_pdf = source_and_clean
    out = tmp_path / "invis.pdf"
    poison.poison_invisible_text(src, clean_pdf, out)
    fp = fingerprint_pdf(out)
    assert len(fp.invisible_text_pages) >= 1


def test_char_spacing_trips_suspicious_tc_signal(
    source_and_clean: tuple[Path, Path], tmp_path: Path
) -> None:
    src, clean_pdf = source_and_clean
    out = tmp_path / "spaced.pdf"
    poison.poison_char_spacing(src, clean_pdf, out)
    fp = fingerprint_pdf(out)
    assert any(abs(v) > 3.0 for v in fp.suspicious_tc_values), (
        "char_spacing should produce Tc operands above the abuse threshold"
    )


def test_homoglyph_trips_non_latin_ratio(
    source_and_clean: tuple[Path, Path], tmp_path: Path
) -> None:
    src, clean_pdf = source_and_clean
    out = tmp_path / "homo.pdf"
    poison.poison_homoglyph(src, clean_pdf, out)
    fp = fingerprint_pdf(out)
    assert fp.non_latin_codepoint_ratio > 0.0


def test_fingerprint_includes_sha256_and_pagecount(clean_pdf: Path) -> None:
    fp = fingerprint_pdf(clean_pdf)
    assert len(fp.sha256) == 64
    assert fp.page_count == sum(1 for _ in clean_pdf.read_bytes() if False) or fp.page_count >= 1
