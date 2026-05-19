"""Convert an OlmOCR workspace's output into benchmark-row JSONL.

OlmOCR doesn't fit the in-process ``Extractor`` protocol — it's a vLLM
batch pipeline that requires a CUDA GPU and runs once over many PDFs.
We invoke it externally (in a Kaggle / Colab notebook with a free T4
GPU) and use *this* importer to convert the per-document outputs into
the same row schema the rest of the benchmark uses.

OlmOCR writes dolma-doc-shaped JSONL (one JSON object per processed
document) into ``<workspace>/results/*.jsonl``. Each row contains at
least ``text`` (the extracted plaintext / markdown), ``id``, and
``metadata.Source-File`` pointing back to the input PDF path. We derive
``source_id`` and ``variant`` from the PDF path layout
(``<corpus>/clean/<sid>.pdf`` or
``<corpus>/poisoned/<technique>/<sid>.pdf``), score the text against the
ground-truth manifest, and emit rows with ``extractor: "olmocr"`` ready
to merge into the main benchmark JSONL.

Wall-time per row is populated from OlmOCR's per-document timing if it
appears under ``metadata`` (the upstream package has tagged this under
varying field names across releases); otherwise the row's
``wall_seconds`` is left at ``None``.

Usage (programmatic):

    from pdf_plaintext_extraction.benchmark.olmocr_importer import (
        import_olmocr_workspace,
    )
    rows = import_olmocr_workspace(
        workspace=Path("olmocr_workspace"),
        corpus_root=default_corpus_cache_dir(),
        out_jsonl=Path("olmocr_rows.jsonl"),
    )

Usage (CLI — for running the merge on a downloaded artifact):

    python -m pdf_plaintext_extraction.benchmark.olmocr_importer \\
        --workspace olmocr_workspace \\
        --out experiments/results/olmocr_kaggle.jsonl
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from collections.abc import Iterable
from pathlib import Path

from pdf_plaintext_extraction._paths import default_corpus_cache_dir
from pdf_plaintext_extraction.benchmark.score import score_against_ground_truth
from pdf_plaintext_extraction.synthesize.ground_truth import build_all

EXTRACTOR_NAME = "olmocr"

# Field names OlmOCR has used across releases for the source-PDF path.
_SOURCE_PATH_KEYS = ("Source-File", "source_file", "source", "filename")

# Field names that may carry per-document wall-time in seconds.
_WALL_TIME_KEYS = (
    "wall_seconds",
    "elapsed_seconds",
    "processing_time_seconds",
    "elapsed",
)


def _extract_source_path(doc: dict) -> str | None:
    """Find the source-PDF path embedded in a dolma doc.

    Looks at the top level and under ``metadata``. Returns the first
    string-valued match.
    """
    for k in _SOURCE_PATH_KEYS:
        v = doc.get(k)
        if isinstance(v, str):
            return v
    meta = doc.get("metadata") or {}
    if isinstance(meta, dict):
        for k in _SOURCE_PATH_KEYS:
            v = meta.get(k)
            if isinstance(v, str):
                return v
    return None


def _extract_wall_seconds(doc: dict) -> float | None:
    for k in _WALL_TIME_KEYS:
        v = doc.get(k)
        if isinstance(v, int | float):
            return float(v)
    meta = doc.get("metadata") or {}
    if isinstance(meta, dict):
        for k in _WALL_TIME_KEYS:
            v = meta.get(k)
            if isinstance(v, int | float):
                return float(v)
    return None


def parse_pdf_path(pdf_path: str | Path) -> tuple[str, str]:
    """Derive ``(source_id, variant)`` from a corpus PDF path.

    Expects paths shaped like
    ``<anything>/clean/<source_id>.pdf`` or
    ``<anything>/poisoned/<technique>/<source_id>.pdf``.

    Raises ``ValueError`` if the path doesn't fit either shape.
    """
    p = Path(pdf_path)
    parts = p.parts
    # Walk from the end so we tolerate arbitrary corpus-root prefixes.
    for i in range(len(parts) - 1, -1, -1):
        if parts[i] == "clean":
            return (p.stem, "clean")
        if parts[i] == "poisoned" and i + 1 < len(parts):
            return (p.stem, parts[i + 1])
    raise ValueError(
        f"cannot parse corpus path {pdf_path!r}: expected '.../clean/<id>.pdf' "
        "or '.../poisoned/<technique>/<id>.pdf'"
    )


def _iter_workspace_docs(workspace: Path) -> Iterable[dict]:
    """Yield dolma-doc JSON objects from every ``*.jsonl`` under
    ``<workspace>/results/`` (or, if ``results/`` doesn't exist, every
    ``*.jsonl`` directly under the workspace)."""
    candidates = list((workspace / "results").glob("*.jsonl"))
    if not candidates:
        candidates = list(workspace.glob("*.jsonl"))
    if not candidates:
        raise FileNotFoundError(f"no *.jsonl files under {workspace} or {workspace}/results")
    for jsonl in sorted(candidates):
        with jsonl.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as e:
                    # Don't drop the whole file for one bad row — log
                    # and continue.
                    print(
                        f"warn: skipping malformed json in {jsonl}: {e}",
                        file=sys.stderr,
                    )


def import_olmocr_workspace(
    workspace: Path,
    corpus_root: Path | None = None,
    out_jsonl: Path | None = None,
    *,
    strict: bool = False,
) -> list[dict]:
    """Convert an OlmOCR workspace into benchmark-schema rows.

    ``corpus_root`` defaults to ``default_corpus_cache_dir()`` — the
    same location the local benchmark uses.

    Returns the list of rows. When ``out_jsonl`` is given, also writes
    them in JSONL form (overwriting any existing file at that path).

    If ``strict`` is True, raises on any source_id present in the
    ground-truth manifest that has no matching olmocr row, and vice
    versa. Otherwise emits warnings on stderr and continues.
    """
    corpus_root = corpus_root or default_corpus_cache_dir()
    entries = build_all(corpus_root)
    by_id = {e.source_id: e for e in entries}

    rows: list[dict] = []
    seen_keys: set[tuple[str, str]] = set()
    for doc in _iter_workspace_docs(workspace):
        text = doc.get("text") or ""
        pdf_path = _extract_source_path(doc)
        if pdf_path is None:
            if strict:
                raise ValueError(f"no source path in doc id {doc.get('id')!r}")
            print(f"warn: no source path in doc id {doc.get('id')!r}", file=sys.stderr)
            continue
        try:
            source_id, variant = parse_pdf_path(pdf_path)
        except ValueError as e:
            if strict:
                raise
            print(f"warn: {e}", file=sys.stderr)
            continue

        entry = by_id.get(source_id)
        if entry is None:
            if strict:
                raise KeyError(f"source_id {source_id!r} not in ground-truth manifest")
            print(
                f"warn: source_id {source_id!r} not in ground-truth manifest",
                file=sys.stderr,
            )
            continue

        seen_keys.add((source_id, variant))
        score = score_against_ground_truth(EXTRACTOR_NAME, pdf_path, text, entry.normalized_text)
        wall_seconds = _extract_wall_seconds(doc)
        row = {
            "source_id": source_id,
            "variant": variant,
            "extractor": EXTRACTOR_NAME,
            "pdf_path": pdf_path,
            "wall_seconds": wall_seconds,
            "error": None,
            **{k: v for k, v in dataclasses.asdict(score).items() if k != "extractor"},
        }
        rows.append(row)

    # Sanity check: did we get every corpus cell?
    expected_keys: set[tuple[str, str]] = set()
    for entry in entries:
        if entry.clean_pdf_path:
            expected_keys.add((entry.source_id, "clean"))
        for v in entry.poisoned:
            expected_keys.add((entry.source_id, v.technique))
    missing = expected_keys - seen_keys
    if missing:
        msg = f"olmocr workspace is missing {len(missing)} cell(s) — first 5: {sorted(missing)[:5]}"
        if strict:
            raise RuntimeError(msg)
        print(f"warn: {msg}", file=sys.stderr)

    if out_jsonl is not None:
        out_jsonl.parent.mkdir(parents=True, exist_ok=True)
        with out_jsonl.open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row) + "\n")

    return rows


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--workspace", type=Path, required=True, help="OlmOCR workspace dir")
    p.add_argument(
        "--corpus-root",
        type=Path,
        default=None,
        help="Materialized corpus root (default: platformdirs user cache dir)",
    )
    p.add_argument("--out", type=Path, required=True, help="Output JSONL path")
    p.add_argument(
        "--strict",
        action="store_true",
        help="Fail on any missing cell or malformed input (default: warn + continue)",
    )
    args = p.parse_args()
    rows = import_olmocr_workspace(
        workspace=args.workspace,
        corpus_root=args.corpus_root,
        out_jsonl=args.out,
        strict=args.strict,
    )
    print(f"wrote {len(rows)} rows -> {args.out}")


if __name__ == "__main__":
    main()
