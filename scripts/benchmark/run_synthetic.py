"""End-to-end synthetic benchmark run.

For every source in ``data/synthetic/sources/`` and every PDF variant
(clean + each implemented poisoning technique), run every extractor in
the default set and score the output against the ground-truth source
text. Writes per-(extractor, variant, source) rows to
``experiments/results/synthetic_<timestamp>.jsonl`` and prints a summary
table.

Usage:

    python -m scripts.benchmark.run_synthetic
    python -m scripts.benchmark.run_synthetic --extractors pypdf,pdftotext
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
from collections import defaultdict
from pathlib import Path

from scripts.benchmark.base import Extractor
from scripts.benchmark.extractors import default_extractors
from scripts.benchmark.score import score_against_ground_truth
from scripts.synthesize.ground_truth import build_all

ROOT = Path(__file__).resolve().parents[2]
RESULTS_DIR = ROOT / "experiments" / "results"


def _select(extractors: list[Extractor], names: list[str] | None) -> list[Extractor]:
    if not names:
        return extractors
    by_name = {e.name: e for e in extractors}
    out = []
    for n in names:
        if n not in by_name:
            raise SystemExit(f"unknown extractor {n!r}; known: {sorted(by_name)}")
        out.append(by_name[n])
    return out


def run(extractors: list[Extractor], out_path: Path) -> list[dict]:
    entries = build_all()
    rows: list[dict] = []

    for entry in entries:
        reference = entry.normalized_text
        # Clean PDF variant
        if entry.clean_pdf_path:
            rows.extend(
                _eval_variant(
                    extractors,
                    pdf=ROOT / entry.clean_pdf_path,
                    source_id=entry.source_id,
                    variant="clean",
                    reference=reference,
                )
            )
        # Poisoned variants
        for variant in entry.poisoned:
            rows.extend(
                _eval_variant(
                    extractors,
                    pdf=ROOT / variant.path,
                    source_id=entry.source_id,
                    variant=variant.technique,
                    reference=reference,
                )
            )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")

    return rows


def _eval_variant(
    extractors: list[Extractor],
    pdf: Path,
    source_id: str,
    variant: str,
    reference: str,
) -> list[dict]:
    out: list[dict] = []
    for ext in extractors:
        result = ext.extract(pdf)
        score = score_against_ground_truth(ext.name, str(pdf), result.text, reference)
        row = {
            "source_id": source_id,
            "variant": variant,
            "extractor": ext.name,
            "pdf_path": str(pdf.relative_to(ROOT)),
            "wall_seconds": round(result.wall_seconds, 3),
            "error": result.error,
            **{k: v for k, v in dataclasses.asdict(score).items() if k != "extractor"},
        }
        out.append(row)
    return out


def _print_summary(rows: list[dict]) -> None:
    by_pair: dict[tuple[str, str], list[float]] = defaultdict(list)
    error_counts: dict[str, dict[str, str]] = defaultdict(dict)

    all_extractors = sorted({r["extractor"] for r in rows})
    all_variants = sorted({r["variant"] for r in rows})

    for r in rows:
        if r["error"]:
            # Keep the first error message per extractor for a footnote
            error_counts[r["extractor"]].setdefault("msg", r["error"])
            error_counts[r["extractor"]]["count"] = (
                int(error_counts[r["extractor"]].get("count", 0)) + 1
            )
            continue
        by_pair[(r["extractor"], r["variant"])].append(r["f1"])

    col_width = max(13, *(len(v) for v in all_variants))
    print()
    print("Mean token F1 by extractor × variant (synthetic gold set):")
    print()
    header = f"  {'extractor':13s} " + " ".join(f"{v:>{col_width}s}" for v in all_variants)
    print(header)
    print("  " + "-" * (len(header) - 2))
    for ex in all_extractors:
        cells = []
        for v in all_variants:
            vals = by_pair.get((ex, v), [])
            if not vals:
                cells.append(f"{'skip':>{col_width}s}")
            else:
                cells.append(f"{sum(vals) / len(vals):>{col_width}.3f}")
        print(f"  {ex:13s} " + " ".join(cells))
    print()

    if error_counts:
        print("Skipped (extractor returned error on every input):")
        for ex, info in sorted(error_counts.items()):
            msg = (info["msg"] or "").split("\n", 1)[0]
            print(f"  {ex:13s} {info['count']} rows  — {msg}")
        print()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--extractors", type=str, default=None, help="comma-separated extractor names")
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="output JSONL path; defaults to experiments/results/synthetic_<ts>.jsonl",
    )
    args = p.parse_args()

    names = args.extractors.split(",") if args.extractors else None
    extractors = _select(default_extractors(), names)
    out = args.out or (
        RESULTS_DIR / f"synthetic_{dt.datetime.now().strftime('%Y%m%dT%H%M%S')}.jsonl"
    )
    rows = run(extractors, out)
    print(f"wrote {len(rows)} rows -> {out.relative_to(ROOT)}")
    _print_summary(rows)


if __name__ == "__main__":
    main()
