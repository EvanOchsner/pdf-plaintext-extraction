"""Tests for the OlmOCR-workspace importer.

We don't need olmocr installed locally — the importer just reads JSONL.
The tests build a tiny fake "olmocr workspace" + tiny corpus root in a
tmpdir and verify the importer produces correctly-keyed rows in the
benchmark schema.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pdf_plaintext_extraction.benchmark.olmocr_importer import (
    import_olmocr_workspace,
    parse_pdf_path,
)

# --- parse_pdf_path -----------------------------------------------------


def test_parse_pdf_path_clean() -> None:
    sid, variant = parse_pdf_path("/x/y/corpus/clean/usc-7-1508.pdf")
    assert sid == "usc-7-1508"
    assert variant == "clean"


def test_parse_pdf_path_poisoned() -> None:
    sid, variant = parse_pdf_path("/x/y/corpus/poisoned/rasterize/wikipedia-volcano.pdf")
    assert sid == "wikipedia-volcano"
    assert variant == "rasterize"


def test_parse_pdf_path_rejects_unknown_shape() -> None:
    with pytest.raises(ValueError, match="cannot parse corpus path"):
        parse_pdf_path("/some/random/path.pdf")


# --- import_olmocr_workspace -------------------------------------------


def _fake_corpus(tmp_path: Path) -> tuple[Path, Path]:
    """Build a tiny materialized corpus with 1 source × 2 variants
    (clean + rasterize). Returns ``(corpus_root, source_pdf_dir)``.
    """
    # Source text (the importer's ground-truth comes via build_all,
    # which globs the package's data/sources/*.txt and matches by id —
    # so we use a real source_id that exists in the package).
    # Picking 'gutenberg-pg11-ch1' which we know is committed.
    corpus = tmp_path / "corpus"
    (corpus / "clean").mkdir(parents=True)
    (corpus / "poisoned" / "rasterize").mkdir(parents=True)
    # The corpus PDFs don't need to actually exist for the importer
    # (it only reads JSONL); but ground_truth.build_all expects them to
    # discover entries, so we create empty placeholder files.
    (corpus / "clean" / "gutenberg-pg11-ch1.pdf").write_bytes(b"%PDF-fake\n")
    (corpus / "poisoned" / "rasterize" / "gutenberg-pg11-ch1.pdf").write_bytes(b"%PDF-fake\n")
    return corpus, corpus / "clean"


def _fake_workspace(
    tmp_path: Path,
    corpus_root: Path,
    *,
    include_rasterize: bool = True,
    extra_text: str = "",
) -> Path:
    """Build a fake olmocr workspace with dolma-doc JSONL output."""
    workspace = tmp_path / "olmocr_workspace"
    results = workspace / "results"
    results.mkdir(parents=True)

    src_text = (
        Path(__file__).resolve().parents[1]
        / "pdf_plaintext_extraction"
        / "data"
        / "sources"
        / "gutenberg-pg11-ch1.txt"
    ).read_text(encoding="utf-8")
    # For "clean", the perfect-extraction case: hand olmocr the source
    # back verbatim. For rasterize, simulate a slight OCR drift.
    # NB: the top-level "source": "olmocr" field is part of the real
    # dolma-doc schema (it names the pipeline, not a file). The importer
    # must NOT mistake it for the source-PDF path — these fixtures keep
    # it present so that regression is caught.
    docs = [
        {
            "id": "doc1",
            "text": src_text + extra_text,
            "source": "olmocr",
            "metadata": {
                "Source-File": str(corpus_root / "clean" / "gutenberg-pg11-ch1.pdf"),
                "wall_seconds": 12.5,
            },
        }
    ]
    if include_rasterize:
        docs.append(
            {
                "id": "doc2",
                # Drop a token to simulate OCR loss
                "text": " ".join(src_text.split()[:-3]),
                "source": "olmocr",
                "metadata": {
                    "Source-File": str(
                        corpus_root / "poisoned" / "rasterize" / "gutenberg-pg11-ch1.pdf"
                    ),
                    "wall_seconds": 18.3,
                },
            }
        )

    out = results / "out-0001.jsonl"
    with out.open("w", encoding="utf-8") as fh:
        for d in docs:
            fh.write(json.dumps(d) + "\n")
    return workspace


def test_import_olmocr_workspace_produces_rows(tmp_path: Path) -> None:
    corpus, _ = _fake_corpus(tmp_path)
    workspace = _fake_workspace(tmp_path, corpus)

    rows = import_olmocr_workspace(workspace=workspace, corpus_root=corpus)

    # 2 rows, one per variant
    assert len(rows) == 2
    by_variant = {r["variant"]: r for r in rows}
    assert set(by_variant) == {"clean", "rasterize"}

    # Verify schema completeness
    clean = by_variant["clean"]
    assert clean["extractor"] == "olmocr"
    assert clean["source_id"] == "gutenberg-pg11-ch1"
    assert clean["pdf_path"].endswith("clean/gutenberg-pg11-ch1.pdf")
    assert clean["wall_seconds"] == 12.5
    assert clean["error"] is None
    # Verbatim text → F1 should be 1.0
    assert clean["f1"] == pytest.approx(1.0)
    assert clean["ned"] == pytest.approx(0.0)

    raster = by_variant["rasterize"]
    # Dropped 3 tokens → F1 should be slightly below 1
    assert 0.99 < raster["f1"] < 1.0


def test_import_olmocr_workspace_writes_jsonl(tmp_path: Path) -> None:
    corpus, _ = _fake_corpus(tmp_path)
    workspace = _fake_workspace(tmp_path, corpus)
    out = tmp_path / "olmocr_rows.jsonl"

    rows = import_olmocr_workspace(workspace=workspace, corpus_root=corpus, out_jsonl=out)
    assert out.exists()
    lines = [json.loads(line) for line in out.open(encoding="utf-8") if line.strip()]
    assert len(lines) == len(rows) == 2


def test_import_olmocr_workspace_strict_flags_missing_cell(tmp_path: Path) -> None:
    corpus, _ = _fake_corpus(tmp_path)
    # Build workspace WITHOUT the rasterize variant — expected cell missing.
    workspace = _fake_workspace(tmp_path, corpus, include_rasterize=False)

    # strict=False: warns + continues, still returns 1 row.
    rows = import_olmocr_workspace(workspace=workspace, corpus_root=corpus, strict=False)
    assert len(rows) == 1

    # strict=True: raises because a corpus cell has no matching olmocr row.
    with pytest.raises(RuntimeError, match="missing"):
        import_olmocr_workspace(workspace=workspace, corpus_root=corpus, strict=True)


def test_import_olmocr_workspace_handles_extra_text(tmp_path: Path) -> None:
    """Adding noise tokens to olmocr output should drop F1 but not crash."""
    corpus, _ = _fake_corpus(tmp_path)
    workspace = _fake_workspace(tmp_path, corpus, extra_text=" WATERMARK OLMOCR EXTRACTED THIS")
    rows = import_olmocr_workspace(workspace=workspace, corpus_root=corpus)
    clean = next(r for r in rows if r["variant"] == "clean")
    assert clean["f1"] < 1.0  # 4 extra tokens lower F1
    assert clean["f1"] > 0.95  # but not by much
