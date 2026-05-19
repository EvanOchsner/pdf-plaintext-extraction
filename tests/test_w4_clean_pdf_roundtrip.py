"""Smoke test: the W4 synthetic clean PDF round-trips to its source text.

For each source under ``pdf_plaintext_extraction/data/sources/``, we
render to a clean PDF, extract it back with pypdf, and assert the token
F1 between the normalized extracted text and the normalized source text
is at least 0.95. This is the harness control: any extractor that scores
substantially below the clean baseline on the same PDF points to a bug
or to a real extraction failure that's worth investigating.

The threshold is intentionally not 1.000. At n=100 sources covering many
scripts, a small number of round-trip imperfections are expected (Arabic
ligature reordering not understood by pypdf, occasional URL line-wrap
artifacts, etc.) — these are font/renderer limitations rather than test
failures.

Also asserts that clean-PDF rendering is byte-deterministic — re-rendering
the same source produces an identical SHA-256.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from pypdf import PdfReader

from pdf_plaintext_extraction._paths import package_sources_dir
from pdf_plaintext_extraction.benchmark.score import token_f1
from pdf_plaintext_extraction.synthesize.clean_pdf import render
from pdf_plaintext_extraction.synthesize.ground_truth import normalize

SOURCES_DIR = package_sources_dir()


def _source_files() -> list[Path]:
    if not SOURCES_DIR.exists():
        return []
    return sorted(SOURCES_DIR.glob("*.txt"))


SOURCES = _source_files()


@pytest.mark.skipif(not SOURCES, reason="seed corpus not fetched yet")
@pytest.mark.parametrize("source", SOURCES, ids=lambda p: p.stem)
def test_clean_pdf_roundtrip(tmp_path: Path, source: Path) -> None:
    out = tmp_path / f"{source.stem}.pdf"
    result = render(source, out)
    assert result.page_count >= 1

    reader = PdfReader(str(out))
    extracted = "\n".join(p.extract_text() for p in reader.pages)

    src_norm = normalize(source.read_text(encoding="utf-8"))
    ext_norm = normalize(extracted)
    f1 = token_f1(ext_norm, src_norm)
    # 95/100 sources hit exact byte match; the remaining ~5 lose <1% F1
    # to renderer line-wrap quirks on long URLs etc. — well above 0.99.
    assert f1 >= 0.99, (
        f"clean-PDF F1 for {source.name} below threshold: got {f1:.3f}.\n"
        f"  expected: {src_norm[:120]!r}\n"
        f"  got:      {ext_norm[:120]!r}"
    )


@pytest.mark.skipif(not SOURCES, reason="seed corpus not fetched yet")
def test_clean_pdf_is_deterministic(tmp_path: Path) -> None:
    source = SOURCES[0]
    a = render(source, tmp_path / "a.pdf")
    b = render(source, tmp_path / "b.pdf")
    assert a.sha256 == b.sha256

    raw_a = hashlib.sha256((tmp_path / "a.pdf").read_bytes()).hexdigest()
    raw_b = hashlib.sha256((tmp_path / "b.pdf").read_bytes()).hexdigest()
    assert raw_a == raw_b == a.sha256
