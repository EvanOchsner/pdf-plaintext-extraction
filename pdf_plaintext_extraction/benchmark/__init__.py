"""Public benchmark API for downstream consumers.

The main entry points for users (PAT, third-party extractor authors)
are:

- :func:`ensure_corpus` — materialize clean + poisoned PDFs into a
  user-cache directory; idempotent.
- :func:`iter_ground_truth` — yield :class:`GroundTruthEntry` records
  with absolute paths resolved against the corpus root.
- :func:`token_f1`, :func:`normalized_edit_distance`,
  :func:`normalize_text`, :func:`tokenize` — scoring primitives,
  re-exported from :mod:`pdf_plaintext_extraction.benchmark.score`.

Typical usage::

    from pdf_plaintext_extraction.benchmark import (
        ensure_corpus, iter_ground_truth, token_f1,
    )

    corpus = ensure_corpus()
    for entry in iter_ground_truth(corpus):
        for variant in entry.poisoned:
            text = my_extractor.extract(variant.path)
            f1 = token_f1(text, entry.normalized_text)
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from pdf_plaintext_extraction._paths import (
    corpus_paths,
    default_corpus_cache_dir,
    package_sources_dir,
)
from pdf_plaintext_extraction.benchmark.score import (  # noqa: F401  re-export
    GroundTruthScore,
    normalize_text,
    normalized_edit_distance,
    score_against_ground_truth,
    token_f1,
    tokenize,
)
from pdf_plaintext_extraction.synthesize.clean_pdf import render
from pdf_plaintext_extraction.synthesize.ground_truth import (
    GroundTruthEntry,
    PoisonedVariant,
    build_all,
)
from pdf_plaintext_extraction.synthesize.ground_truth import (
    write as _write_manifest,
)
from pdf_plaintext_extraction.synthesize.poison import (
    TECHNIQUES,
    apply_all_implemented,
)

__all__ = [
    "ensure_corpus",
    "iter_ground_truth",
    "corpus_cache_dir",
    "GroundTruthEntry",
    "PoisonedVariant",
    "GroundTruthScore",
    "token_f1",
    "normalized_edit_distance",
    "normalize_text",
    "tokenize",
    "score_against_ground_truth",
]


def corpus_cache_dir() -> Path:
    """Return the default corpus root (under platformdirs user cache)."""
    return default_corpus_cache_dir()


def ensure_corpus(
    *,
    cache_dir: Path | None = None,
    regenerate: bool = False,
) -> Path:
    """Materialize clean + poisoned PDFs into ``cache_dir``.

    Returns the corpus root (a directory containing ``clean/``,
    ``poisoned/<technique>/`` and ``ground_truth.jsonl``). Idempotent:
    if every artifact named in the manifest already exists and its
    SHA-256 matches, this is a no-op.

    Parameters
    ----------
    cache_dir:
        Where to write the corpus. Default: platformdirs user cache.
    regenerate:
        If True, rebuild every artifact even if hashes match.
    """
    corpus_root = Path(cache_dir) if cache_dir else default_corpus_cache_dir()
    paths = corpus_paths(corpus_root)
    paths["clean"].mkdir(parents=True, exist_ok=True)
    paths["poisoned"].mkdir(parents=True, exist_ok=True)

    sources_dir = package_sources_dir()
    source_ids = sorted(p.stem for p in sources_dir.glob("*.txt"))
    if not source_ids:
        raise FileNotFoundError(f"no source texts in bundled package data: {sources_dir}")

    # 1. Clean PDFs.
    for sid in source_ids:
        clean_pdf = paths["clean"] / f"{sid}.pdf"
        if clean_pdf.exists() and not regenerate:
            continue
        render(sources_dir / f"{sid}.txt", clean_pdf, title=sid)

    # 2. Poisoned PDFs — one call per source_id renders all techniques.
    for sid in source_ids:
        needs_any = regenerate or any(
            not (paths["poisoned"] / technique / f"{sid}.pdf").exists() for technique in TECHNIQUES
        )
        if needs_any:
            apply_all_implemented(sid, corpus_root)

    # 3. Write/refresh manifest. build_all reads what's on disk.
    entries = build_all(corpus_root)
    _write_manifest(entries, paths["ground_truth"])
    return corpus_root


def iter_ground_truth(corpus_root: Path) -> Iterator[GroundTruthEntry]:
    """Yield manifest entries with paths resolved against ``corpus_root``.

    ``entry.clean_pdf_path`` and ``variant.path`` come back as absolute
    paths a caller can open directly; ``entry.source_path`` resolves to
    the bundled package data.
    """
    corpus_root = Path(corpus_root)
    paths = corpus_paths(corpus_root)
    manifest = paths["ground_truth"]
    if not manifest.exists():
        raise FileNotFoundError(f"no manifest at {manifest}; call ensure_corpus() first")

    import json

    sources_dir = package_sources_dir()
    with manifest.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            raw = json.loads(line)
            poisoned = [
                PoisonedVariant(
                    technique=v["technique"],
                    path=str(corpus_root / v["path"]),
                    sha256=v["sha256"],
                )
                for v in raw.get("poisoned", [])
            ]
            entry = GroundTruthEntry(
                source_id=raw["source_id"],
                source_path=str(sources_dir / Path(raw["source_path"]).name),
                source_sha256=raw["source_sha256"],
                normalized_text=raw["normalized_text"],
                word_count=raw["word_count"],
                clean_pdf_path=(
                    str(corpus_root / raw["clean_pdf_path"]) if raw.get("clean_pdf_path") else None
                ),
                clean_pdf_sha256=raw.get("clean_pdf_sha256"),
                poisoned=poisoned,
            )
            yield entry
