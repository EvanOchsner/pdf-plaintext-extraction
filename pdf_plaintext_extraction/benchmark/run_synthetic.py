"""End-to-end synthetic benchmark run.

For every bundled source text and every materialized PDF variant
(clean + each implemented poisoning technique), run every extractor in
the default set and score the output against the ground-truth source
text. Writes per-(extractor, variant, source) rows to
``experiments/results/synthetic_<timestamp>.jsonl`` and prints a summary
table.

Materialize the corpus first with
``pdf_plaintext_extraction.benchmark.ensure_corpus`` (or pass
``--corpus-root``).

Usage:

    python -m pdf_plaintext_extraction.benchmark.run_synthetic
    python -m pdf_plaintext_extraction.benchmark.run_synthetic --extractors pypdf,pdftotext
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import datetime as dt
import json
import sys
from collections import defaultdict
from pathlib import Path

from pdf_plaintext_extraction._paths import default_corpus_cache_dir
from pdf_plaintext_extraction.benchmark.base import Extractor
from pdf_plaintext_extraction.benchmark.extractors import default_extractors
from pdf_plaintext_extraction.benchmark.score import score_against_ground_truth
from pdf_plaintext_extraction.synthesize.ground_truth import build_all

# Repo-root resolution still works in dev mode (editable install);
# results land under the cwd's experiments/ when run from the repo.
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


def _load_done_cells(jsonl_path: Path) -> set[tuple[str, str, str]]:
    """Read an existing results JSONL and return the set of
    (extractor, source_id, variant) cells already present (regardless of
    whether they errored — the row is the record of work attempted).
    Used by ``--resume`` to skip cells that crashed runs already covered.
    """
    done: set[tuple[str, str, str]] = set()
    if not jsonl_path.exists():
        return done
    with jsonl_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            done.add((r["extractor"], r["source_id"], r["variant"]))
    return done


def run(
    extractors: list[Extractor],
    out_path: Path,
    corpus_root: Path,
    resume: bool = False,
    source_limit: int | None = None,
) -> list[dict]:
    entries = build_all(corpus_root)
    if source_limit is not None:
        # First N source_ids (sorted). Matches the ``--sources`` semantics
        # of ``benchmark.olmocr_mlx`` so the two runs cover the identical
        # subset and their timings are directly comparable.
        entries = sorted(entries, key=lambda e: e.source_id)[:source_limit]
    rows: list[dict] = []

    # ``--resume`` reuses the same output file by appending and skipping
    # any (extractor, source_id, variant) cell already present. The
    # done-set is keyed on extractor too so adding new extractors later
    # only triggers work on the new ones for each existing cell.
    done_cells: set[tuple[str, str, str]] = set()
    open_mode = "w"
    if resume and out_path.exists():
        done_cells = _load_done_cells(out_path)
        if done_cells:
            open_mode = "a"
            print(
                f"resume: {len(done_cells)} (extractor,source,variant) rows already present; skipping those",
                file=sys.stderr,
                flush=True,
            )
            # Pre-populate ``rows`` with the existing data so the in-memory
            # list reflects everything for the final summary.
            with out_path.open(encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        with contextlib.suppress(json.JSONDecodeError):
                            rows.append(json.loads(line))

    # Open the output JSONL once and append after each (source × variant)
    # cell completes — this way a crash 5 hours into a 6-hour run still
    # leaves the partial results on disk.
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open(open_mode, encoding="utf-8") as fh:
        total_cells = sum((1 if e.clean_pdf_path else 0) + len(e.poisoned) for e in entries)
        cell_idx = 0

        def _process_cell(entry, pdf_path, variant_name):
            nonlocal cell_idx
            cell_idx += 1
            # Filter to extractors whose row for this cell isn't already on disk.
            todo = [
                ex
                for ex in extractors
                if (ex.name, entry.source_id, variant_name) not in done_cells
            ]
            if not todo:
                print(
                    f"[{cell_idx}/{total_cells}] {entry.source_id}/{variant_name} (skipped, all extractors already done)",
                    file=sys.stderr,
                    flush=True,
                )
                return
            cell = _eval_variant(
                todo,
                pdf=pdf_path,
                source_id=entry.source_id,
                variant=variant_name,
                reference=entry.normalized_text,
            )
            for row in cell:
                fh.write(json.dumps(row) + "\n")
            fh.flush()
            rows.extend(cell)
            partial = (
                ""
                if len(todo) == len(extractors)
                else f"  ({len(todo)}/{len(extractors)} extractors)"
            )
            print(
                f"[{cell_idx}/{total_cells}] {entry.source_id}/{variant_name} done{partial}",
                file=sys.stderr,
                flush=True,
            )

        for entry in entries:
            if entry.clean_pdf_path:
                _process_cell(entry, corpus_root / entry.clean_pdf_path, "clean")
            for variant in entry.poisoned:
                _process_cell(entry, corpus_root / variant.path, variant.technique)

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
            "pdf_path": str(pdf),
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
    p.add_argument(
        "--corpus-root",
        type=Path,
        default=None,
        help="Corpus root (default: platformdirs user cache dir)",
    )
    p.add_argument(
        "--resume",
        action="store_true",
        help="Append to --out (must exist); skip any (extractor,source,variant) cells already present.",
    )
    p.add_argument(
        "--sources",
        type=int,
        default=None,
        help="Limit to the first N source_ids (sorted). Omit to run all 100.",
    )
    args = p.parse_args()

    names = args.extractors.split(",") if args.extractors else None
    extractors = _select(default_extractors(), names)
    if args.resume and not args.out:
        raise SystemExit("--resume requires --out <existing-jsonl-path>")
    out = args.out or (
        RESULTS_DIR / f"synthetic_{dt.datetime.now().strftime('%Y%m%dT%H%M%S')}.jsonl"
    )
    corpus_root = args.corpus_root or default_corpus_cache_dir()
    rows = run(extractors, out, corpus_root, resume=args.resume, source_limit=args.sources)
    print(f"wrote {len(rows)} rows -> {out}")
    _print_summary(rows)


if __name__ == "__main__":
    main()
