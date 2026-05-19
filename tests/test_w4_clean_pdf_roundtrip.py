"""Smoke test: the W4 synthetic clean PDF round-trips to its source text.

For each source under ``data/synthetic/sources/``, we render to a clean
PDF, extract it back with pypdf, and assert the normalized extracted text
matches the normalized source text exactly. This is the harness control:
any extractor that fails on the *clean* PDF points to a bug in the
harness or renderer, not to a poisoning effect.

Also asserts that clean-PDF rendering is byte-deterministic — re-rendering
the same source produces an identical SHA-256.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from pypdf import PdfReader

from pdf_plaintext_extraction._paths import package_sources_dir
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
    assert ext_norm == src_norm, (
        f"clean PDF for {source.name} did not round-trip to its source.\n"
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
