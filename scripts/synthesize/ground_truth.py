"""Build the ground-truth manifest for the synthetic gold benchmark set.

For each source text under ``data/synthetic/sources/``, record:

- the canonical normalized text (the ground truth for accuracy scoring),
- the SHA-256 of the source bytes,
- the rendered clean-PDF SHA-256 (if present),
- the list of poisoned variants that have been generated.

Output: ``data/synthetic/ground_truth.jsonl`` — one JSON object per source.

The "canonical normalized text" is a stable normalization of the source:
collapsed whitespace, NFC Unicode, no leading/trailing blanks. Extractors
are scored against this normalization, not the raw bytes, so trailing
newlines or paragraph re-flow aren't penalized.
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

ROOT = Path(__file__).resolve().parents[2]
SOURCES_DIR = ROOT / "data" / "synthetic" / "sources"
CLEAN_DIR = ROOT / "data" / "synthetic" / "clean"
POISONED_DIR = ROOT / "data" / "synthetic" / "poisoned"
GROUND_TRUTH_PATH = ROOT / "data" / "synthetic" / "ground_truth.jsonl"

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


def _discover_poisoned(source_id: str) -> Iterable[PoisonedVariant]:
    if not POISONED_DIR.exists():
        return
    for technique_dir in sorted(POISONED_DIR.iterdir()):
        if not technique_dir.is_dir():
            continue
        candidate = technique_dir / f"{source_id}.pdf"
        if candidate.exists():
            yield PoisonedVariant(
                technique=technique_dir.name,
                path=str(candidate.relative_to(ROOT)),
                sha256=_sha256(candidate),
            )


def build_entry(source_path: Path) -> GroundTruthEntry:
    source_id = source_path.stem
    raw = source_path.read_text(encoding="utf-8")
    normalized = normalize(raw)
    entry = GroundTruthEntry(
        source_id=source_id,
        source_path=str(source_path.relative_to(ROOT)),
        source_sha256=_sha256(source_path),
        normalized_text=normalized,
        word_count=len(normalized.split()),
    )
    clean_pdf = CLEAN_DIR / f"{source_id}.pdf"
    if clean_pdf.exists():
        entry.clean_pdf_path = str(clean_pdf.relative_to(ROOT))
        entry.clean_pdf_sha256 = _sha256(clean_pdf)
    entry.poisoned = list(_discover_poisoned(source_id))
    return entry


def build_all() -> list[GroundTruthEntry]:
    if not SOURCES_DIR.exists():
        raise FileNotFoundError(f"missing sources dir: {SOURCES_DIR}")
    entries = []
    for source in sorted(SOURCES_DIR.glob("*.txt")):
        entries.append(build_entry(source))
    return entries


def write(entries: list[GroundTruthEntry], out: Path = GROUND_TRUTH_PATH) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for entry in entries:
            d = asdict(entry)
            fh.write(json.dumps(d, ensure_ascii=False) + "\n")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, default=GROUND_TRUTH_PATH)
    args = p.parse_args()
    entries = build_all()
    write(entries, args.out)
    print(f"wrote {args.out} with {len(entries)} source(s)")


if __name__ == "__main__":
    main()
