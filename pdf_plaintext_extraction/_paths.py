"""Path resolution for the synthetic-gold corpus.

Two notions of "where the corpus lives":

1. **Source texts** ship inside the wheel as package data under
   ``pdf_plaintext_extraction/data/sources/``. They are always
   available via ``importlib.resources`` after a normal install.

2. **Rendered artifacts** — clean PDFs, poisoned PDFs, the
   ground-truth manifest — are *regenerable* from the source texts.
   They are NOT shipped in the wheel; instead they live in a
   per-user *corpus root* that callers can pick or accept the
   default (``platformdirs.user_cache_dir``).

Callers should prefer ``pdf_plaintext_extraction.benchmark.ensure_corpus()``
over poking these helpers directly.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path


def package_sources_dir() -> Path:
    """Path to the bundled source texts (read-only, inside the wheel)."""
    # ``files()`` on a package returns a Traversable; for installed
    # packages on disk this is a real Path. We require a real Path here
    # because callers iterate with ``glob``.
    res = resources.files("pdf_plaintext_extraction.data.sources")
    return Path(str(res))


def default_corpus_cache_dir() -> Path:
    """Default corpus root under the user cache dir.

    Resolves via ``platformdirs.user_cache_dir`` — cross-platform,
    out-of-tree, persistent across runs. Does NOT create the dir.
    """
    import platformdirs

    return Path(platformdirs.user_cache_dir("pdf-plaintext-extraction")) / "corpus"


def corpus_paths(corpus_root: Path) -> dict[str, Path]:
    """Standard subdirectories inside a corpus root.

    The synthesize pipeline writes here; the benchmark reads from
    here. Callers create the root by calling ``ensure_corpus``.
    """
    corpus_root = Path(corpus_root)
    return {
        "root": corpus_root,
        "sources": corpus_root / "sources",
        "clean": corpus_root / "clean",
        "poisoned": corpus_root / "poisoned",
        "ground_truth": corpus_root / "ground_truth.jsonl",
    }
