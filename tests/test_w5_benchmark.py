"""Smoke tests for the W5 benchmark harness."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.benchmark.extractors import PypdfExtractor
from scripts.benchmark.score import (
    normalized_edit_distance,
    score_against_ground_truth,
    token_f1,
    token_levenshtein,
    tokenize,
)
from scripts.synthesize import poison
from scripts.synthesize.clean_pdf import render

ROOT = Path(__file__).resolve().parents[1]
SOURCES_DIR = ROOT / "data" / "synthetic" / "sources"


def test_token_levenshtein_basic() -> None:
    assert token_levenshtein([], []) == 0
    assert token_levenshtein(["a"], []) == 1
    assert token_levenshtein(["a", "b"], ["a", "b"]) == 0
    assert token_levenshtein(["a", "b"], ["a", "c"]) == 1


def test_token_f1_perfect_and_disjoint() -> None:
    assert token_f1("the quick fox", "the quick fox") == pytest.approx(1.0)
    assert token_f1("a b c", "x y z") == pytest.approx(0.0)


def test_normalized_edit_distance_bounded() -> None:
    assert normalized_edit_distance("", "") == 0.0
    assert normalized_edit_distance("a", "") == 1.0
    assert 0.0 <= normalized_edit_distance("foo bar", "foo baz") <= 1.0


def test_clean_pdf_scores_near_perfect(tmp_path: Path) -> None:
    sources = sorted(SOURCES_DIR.glob("*.txt"))
    if not sources:
        pytest.skip("seed corpus not fetched")
    src = sources[0]
    clean = tmp_path / "clean.pdf"
    render(src, clean)
    reference = src.read_text(encoding="utf-8")
    result = PypdfExtractor().extract(clean)
    score = score_against_ground_truth("pypdf", str(clean), result.text, reference)
    assert score.f1 > 0.99, (
        f"the harness control should score near-perfect on the clean PDF; got f1={score.f1}"
    )
    assert score.ned < 0.02


def test_watermark_degrades_extraction(tmp_path: Path) -> None:
    sources = sorted(SOURCES_DIR.glob("*.txt"))
    if not sources:
        pytest.skip("seed corpus not fetched")
    src = sources[0]
    clean = tmp_path / "clean.pdf"
    render(src, clean)
    poisoned = tmp_path / "poisoned.pdf"
    poison.poison_watermark(src, clean, poisoned)

    reference = src.read_text(encoding="utf-8")
    clean_score = score_against_ground_truth(
        "pypdf", str(clean), PypdfExtractor().extract(clean).text, reference
    )
    poisoned_score = score_against_ground_truth(
        "pypdf", str(poisoned), PypdfExtractor().extract(poisoned).text, reference
    )
    assert poisoned_score.f1 < clean_score.f1, (
        "watermark must measurably degrade extractor F1 relative to clean"
    )


def test_tokenize_normalizes_unicode() -> None:
    # NFC normalization should collapse "café" written two ways into one form
    a = tokenize("café")  # precomposed é
    b = tokenize("café")  # e + combining acute
    assert a == b
