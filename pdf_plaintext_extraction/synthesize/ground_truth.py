"""Build the ground-truth manifest for the synthetic gold benchmark set.

For each source text bundled in ``pdf_plaintext_extraction.data.sources``,
record:

- the canonical normalized text (the ground truth for accuracy scoring),
- the SHA-256 of the source bytes,
- the rendered clean-PDF SHA-256 (if present in the corpus root),
- the list of poisoned variants that have been generated.

Output: ``<corpus_root>/ground_truth.jsonl`` — one JSON object per source.

The "canonical normalized text" is a stable normalization of the source:
collapsed whitespace, NFC Unicode, no leading/trailing blanks. Extractors
are scored against this normalization, not the raw bytes, so trailing
newlines or paragraph re-flow aren't penalized.

Paths inside the manifest are stored *relative to the corpus root*, so
the manifest is portable across machines as long as the consumer
materializes the corpus before reading.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from pdf_plaintext_extraction._paths import (
    corpus_paths,
    default_corpus_cache_dir,
    package_sources_dir,
)

_WHITESPACE = re.compile(r"\s+")


@dataclass
class PoisonedVariant:
    technique: str
    path: str
    sha256: str


@dataclass
class GroundTruthEntry:
    source_id: str
    source_path: str
    source_sha256: str
    normalized_text: str
    word_count: int
    clean_pdf_path: str | None = None
    clean_pdf_sha256: str | None = None
    poisoned: list[PoisonedVariant] = field(default_factory=list)


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = _WHITESPACE.sub(" ", text).strip()
    return text


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _discover_poisoned(source_id: str, poisoned_dir: Path) -> Iterable[PoisonedVariant]:
    if not poisoned_dir.exists():
        return
    for technique_dir in sorted(poisoned_dir.iterdir()):
        if not technique_dir.is_dir():
            continue
        candidate = technique_dir / f"{source_id}.pdf"
        if candidate.exists():
            yield PoisonedVariant(
                technique=technique_dir.name,
                path=str(candidate.relative_to(poisoned_dir.parent)),
                sha256=_sha256(candidate),
            )


def build_entry(source_path: Path, corpus_root: Path) -> GroundTruthEntry:
    paths = corpus_paths(corpus_root)
    source_id = source_path.stem
    raw = source_path.read_text(encoding="utf-8")
    normalized = normalize(raw)
    # ``source_path`` lives inside the wheel; record only the file name
    # under "sources/" so the manifest is portable.
    entry = GroundTruthEntry(
        source_id=source_id,
        source_path=f"sources/{source_path.name}",
        source_sha256=_sha256(source_path),
        normalized_text=normalized,
        word_count=len(normalized.split()),
    )
    clean_pdf = paths["clean"] / f"{source_id}.pdf"
    if clean_pdf.exists():
        entry.clean_pdf_path = str(clean_pdf.relative_to(corpus_root))
        entry.clean_pdf_sha256 = _sha256(clean_pdf)
    entry.poisoned = list(_discover_poisoned(source_id, paths["poisoned"]))
    return entry


def build_all(corpus_root: Path | None = None) -> list[GroundTruthEntry]:
    if corpus_root is None:
        corpus_root = default_corpus_cache_dir()
    sources_dir = package_sources_dir()
    if not sources_dir.exists():
        raise FileNotFoundError(f"missing bundled sources dir: {sources_dir}")
    entries = []
    for source in sorted(sources_dir.glob("*.txt")):
        entries.append(build_entry(source, corpus_root))
    return entries


def write(entries: list[GroundTruthEntry], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for entry in entries:
            d = asdict(entry)
            fh.write(json.dumps(d, ensure_ascii=False) + "\n")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--corpus-root",
        type=Path,
        default=None,
        help="Corpus root (default: platformdirs user cache dir)",
    )
    p.add_argument("--out", type=Path, default=None)
    args = p.parse_args()
    corpus_root = args.corpus_root or default_corpus_cache_dir()
    out = args.out or corpus_paths(corpus_root)["ground_truth"]
    entries = build_all(corpus_root)
    write(entries, out)
    print(f"wrote {out} with {len(entries)} source(s)")


if __name__ == "__main__":
    main()
