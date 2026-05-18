"""Scoring metrics for the W5 benchmark.

Two regimes:

1. **Ground-truth scoring** (synthetic gold set). The source text is
   normalized and compared to the extractor's normalized output via
   token-level F1 and normalized edit distance. The clean PDF is the
   control: every extractor should score near-perfect on it.

2. **Inter-method agreement** (real corpus, no ground truth). For each
   PDF, score each extractor by its pairwise agreement with the other
   extractors. The mean pairwise normalized edit distance becomes a
   proxy for "how much does this extractor agree with the field."

Edit distance uses a pure-Python Levenshtein on token sequences (not
characters) to keep memory bounded for long documents. We deliberately
do NOT pull in `python-Levenshtein` or `rapidfuzz` — token-level is
sufficient for benchmark resolution and uses stdlib only.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable

_WHITESPACE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = _WHITESPACE.sub(" ", text).strip()
    return text


def tokenize(text: str) -> list[str]:
    return normalize_text(text).split()


def token_levenshtein(a: list[str], b: list[str]) -> int:
    """Standard DP Levenshtein over token sequences, O(len(a)*len(b))."""
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    cur = [0] * (len(b) + 1)
    for i, ta in enumerate(a, 1):
        cur[0] = i
        for j, tb in enumerate(b, 1):
            cost = 0 if ta == tb else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
        prev, cur = cur, prev
    return prev[len(b)]


def normalized_edit_distance(a: str, b: str) -> float:
    """Token-level NED in [0, 1]. 0 = identical, 1 = wholly disjoint."""
    ta, tb = tokenize(a), tokenize(b)
    if not ta and not tb:
        return 0.0
    denom = max(len(ta), len(tb))
    return token_levenshtein(ta, tb) / denom


def token_f1(predicted: str, reference: str) -> float:
    """Multiset token F1. Useful when ordering matters less than recall."""
    pred = tokenize(predicted)
    ref = tokenize(reference)
    if not pred and not ref:
        return 1.0
    if not pred or not ref:
        return 0.0
    from collections import Counter

    pred_c = Counter(pred)
    ref_c = Counter(ref)
    overlap = sum((pred_c & ref_c).values())
    if overlap == 0:
        return 0.0
    precision = overlap / sum(pred_c.values())
    recall = overlap / sum(ref_c.values())
    return 2 * precision * recall / (precision + recall)


@dataclass
class GroundTruthScore:
    extractor: str
    pdf_path: str
    ned: float
    f1: float
    ref_word_count: int
    hyp_word_count: int


def score_against_ground_truth(
    extractor_name: str, pdf_path: str, predicted: str, reference: str
) -> GroundTruthScore:
    return GroundTruthScore(
        extractor=extractor_name,
        pdf_path=pdf_path,
        ned=normalized_edit_distance(predicted, reference),
        f1=token_f1(predicted, reference),
        ref_word_count=len(tokenize(reference)),
        hyp_word_count=len(tokenize(predicted)),
    )


def mean_pairwise_ned(
    extractor_name: str, predicted: str, others: Iterable[tuple[str, str]]
) -> float:
    """For inter-method scoring on the real corpus. ``others`` is an
    iterable of (other_extractor_name, other_text). Returns the mean NED
    between ``predicted`` and each other extractor's output, skipping
    self-comparisons.
    """
    diffs = [
        normalized_edit_distance(predicted, text)
        for name, text in others
        if name != extractor_name
    ]
    if not diffs:
        return 0.0
    return sum(diffs) / len(diffs)
