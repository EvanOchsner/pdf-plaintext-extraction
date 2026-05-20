"""Local OlmOCR runner for Apple Silicon (MLX).

OlmOCR's upstream inference path is vLLM + CUDA, which does not run on
Apple Silicon. This module is the macOS counterpart to the Kaggle
notebook path: it loads an MLX-quantized build of
``allenai/olmOCR-2-7B-1025`` (default ``mlx-community/olmOCR-2-7B-1025-8bit``)
via ``mlx-vlm`` and runs it over the synthetic benchmark corpus on the
Mac's own GPU (Metal).

It produces the *same* ``<workspace>/results/*.jsonl`` dolma-doc output
the Kaggle path produces, so :mod:`olmocr_importer` consumes it
unchanged and emits rows with ``extractor: "olmocr"``.

Pipeline, per PDF:

1. Rasterize each page to PNG via ``pypdfium2`` (longest side scaled to
   ``--image-dim`` px — olmOCR-2 expects ~1288).
2. Run the page image + the olmOCR v4 YAML prompt through the MLX model.
3. Strip the YAML front matter the model emits; the body is the page's
   ``natural_text``.
4. Concatenate page texts into one dolma doc; append to the workspace.

The run is resumable: PDFs whose ``Source-File`` already appears in the
workspace JSONL are skipped, so an interrupted multi-hour run picks up
where it left off.

Usage::

    python -m pdf_plaintext_extraction.benchmark.olmocr_mlx \\
        --sources 10 \\
        --out experiments/results/olmocr_mlx.jsonl

``--sources N`` limits the run to the first ``N`` source_ids (×7
variants). Omit it to run the full 700-PDF corpus.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import sys
import time
from pathlib import Path

from pdf_plaintext_extraction._paths import default_corpus_cache_dir
from pdf_plaintext_extraction.benchmark import ensure_corpus
from pdf_plaintext_extraction.benchmark.olmocr_importer import import_olmocr_workspace

# olmOCR-2 default model is the FP8 release (Hopper-only). On Apple
# Silicon we use the MLX-quantized sibling — 8-bit keeps quality within
# ~0.5% of bf16 while fitting comfortably in unified memory.
DEFAULT_MODEL = "mlx-community/olmOCR-2-7B-1025-8bit"

# olmOCR-2 expects a single page image with longest dimension ~1288 px.
DEFAULT_IMAGE_DIM = 1288

# Generation cap. A single corpus page never needs more than this; a
# runaway generation is a sign of a degenerate input, not lost content.
DEFAULT_MAX_TOKENS = 4096

# The exact prompt olmOCR-2 was fine-tuned with — copied verbatim from
# olmocr.prompts.build_no_anchoring_v4_yaml_prompt so we don't take a
# dependency on the (CUDA-heavy) olmocr package.
OLMOCR_V4_PROMPT = (
    "Attached is one page of a document that you must process. "
    "Just return the plain text representation of this document as if you "
    "were reading it naturally. Convert equations to LateX and tables to HTML.\n"
    "If there are any figures or charts, label them with the following "
    "markdown syntax ![Alt text describing the contents of the figure]"
    "(page_startx_starty_width_height.png)\n"
    "Return your output as markdown, with a front matter section on top "
    "specifying values for the primary_language, is_rotation_valid, "
    "rotation_correction, is_table, and is_diagram parameters."
)


def strip_front_matter(markdown: str) -> str:
    """Return the body text, dropping any leading YAML front matter.

    Mirrors ``olmocr.train.front_matter.FrontMatterParser`` — if the
    output opens with ``---\\n`` and has a closing ``\\n---``, everything
    after the closing delimiter is the page's natural text. Otherwise the
    whole string is the text.
    """
    if markdown.startswith("---\n"):
        end = markdown.find("\n---", 4)
        if end != -1:
            return markdown[end + 4 :].strip()
    return markdown.strip()


def render_pdf_pages(pdf_path: Path, out_dir: Path, image_dim: int) -> list[Path]:
    """Rasterize every page of ``pdf_path`` to a PNG under ``out_dir``.

    The longest side of each render is scaled to ``image_dim`` px. Returns
    the page PNG paths in page order.
    """
    import pypdfium2  # local import — heavy, only needed at run time

    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    doc = pypdfium2.PdfDocument(str(pdf_path))
    try:
        for i in range(len(doc)):
            page = doc[i]
            width_pt, height_pt = page.get_size()
            scale = image_dim / max(width_pt, height_pt)
            pil = page.render(scale=scale).to_pil()
            png = out_dir / f"{pdf_path.stem}_p{i + 1:03d}.png"
            pil.save(png)
            paths.append(png)
    finally:
        doc.close()
    return paths


def _load_done_source_files(results_jsonl: Path) -> set[str]:
    """Source-File values already present in the workspace JSONL."""
    done: set[str] = set()
    if not results_jsonl.exists():
        return done
    with results_jsonl.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                doc = json.loads(line)
            except json.JSONDecodeError:
                continue
            src = (doc.get("metadata") or {}).get("Source-File")
            if isinstance(src, str):
                done.add(src)
    return done


def run_olmocr_mlx(
    *,
    corpus_root: Path,
    workspace: Path,
    model_name: str = DEFAULT_MODEL,
    image_dim: int = DEFAULT_IMAGE_DIM,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    source_limit: int | None = None,
    resume: bool = True,
) -> Path:
    """Run the MLX OlmOCR model over the corpus; write dolma-doc JSONL.

    Returns the path to ``<workspace>/results/output_all.jsonl``.
    """
    import mlx.core as mx
    from mlx_vlm import generate, load
    from mlx_vlm.prompt_utils import apply_chat_template
    from mlx_vlm.utils import load_config

    results_dir = workspace / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    out_jsonl = results_dir / "output_all.jsonl"
    render_dir = workspace / "page_renders"

    # Select corpus PDFs. Optionally limit to the first N source_ids so a
    # validation / smoke run stays small.
    all_pdfs = sorted(corpus_root.rglob("*.pdf"))
    if source_limit is not None:
        keep_ids = sorted({p.stem for p in all_pdfs})[:source_limit]
        keep = set(keep_ids)
        all_pdfs = [p for p in all_pdfs if p.stem in keep]

    done = _load_done_source_files(out_jsonl) if resume else set()
    if not resume and out_jsonl.exists():
        out_jsonl.unlink()
    pending = [p for p in all_pdfs if str(p) not in done]

    print(f"Model    : {model_name}")
    print(f"Corpus   : {len(all_pdfs)} PDFs  ({len(done)} already done, {len(pending)} pending)")
    print(f"Workspace: {workspace}")

    if not pending:
        print("Nothing to do — every selected PDF is already in the workspace.")
        return out_jsonl

    # Cap MLX's reusable-buffer cache. On a long unattended run the cache
    # grows unbounded; on a memory-constrained Mac that pushes the model's
    # own buffers into swap, and a swapped GPU buffer stalls its command
    # buffer past the Metal watchdog — surfacing as
    # "kIOGPUCommandBufferCallbackErrorTimeout" and an abort(). A modest
    # cap plus clear_cache() between pages keeps the footprint flat.
    mx.set_cache_limit(1024 * 1024 * 1024)  # 1 GiB

    t_load = time.perf_counter()
    model, processor = load(model_name)
    config = load_config(model_name)
    mx.clear_cache()
    print(f"Model loaded in {time.perf_counter() - t_load:.1f}s\n")

    t_phase = time.perf_counter()
    n_pages_total = 0
    errored: list[tuple[str, str]] = []

    with out_jsonl.open("a", encoding="utf-8") as fout:
        for i, pdf_path in enumerate(pending, start=1):
            pdf_t0 = time.perf_counter()
            try:
                page_pngs = render_pdf_pages(pdf_path, render_dir, image_dim)
                if not page_pngs:
                    errored.append((str(pdf_path), "0 pages"))
                    continue
                page_texts: list[str] = []
                for png in page_pngs:
                    formatted = apply_chat_template(
                        processor, config, OLMOCR_V4_PROMPT, num_images=1
                    )
                    result = generate(
                        model,
                        processor,
                        formatted,
                        [str(png)],
                        max_tokens=max_tokens,
                        temperature=0.0,
                        verbose=False,
                    )
                    page_texts.append(strip_front_matter(result.text))
                    # Return this page's transient buffers to the OS so
                    # the resident footprint stays flat across the run.
                    mx.clear_cache()
            except Exception as e:  # noqa: BLE001 — per-PDF isolation
                err = f"{type(e).__name__}: {e}"
                print(f"  ERROR {pdf_path.name}: {err}")
                errored.append((str(pdf_path), err))
                continue
            finally:
                # Drop page renders for this PDF — they are large and
                # only needed transiently.
                for png in render_dir.glob(f"{pdf_path.stem}_p*.png"):
                    png.unlink(missing_ok=True)

            wall_seconds = time.perf_counter() - pdf_t0
            doc_text = "\n".join(t for t in page_texts if t)
            n_pages_total += len(page_texts)
            if not doc_text:
                errored.append((str(pdf_path), "empty extraction"))
                continue

            now = datetime.datetime.now().strftime("%Y-%m-%d")
            doc = {
                "id": hashlib.sha1(doc_text.encode()).hexdigest(),
                "text": doc_text,
                "source": "olmocr",
                "added": now,
                "created": now,
                "metadata": {
                    "Source-File": str(pdf_path),
                    "olmocr-version": f"mlx:{model_name}",
                    "pdf-total-pages": len(page_texts),
                    "wall_seconds": wall_seconds,
                    "inference": "mlx-vlm",
                    "model": model_name,
                    "image_dim": image_dim,
                },
            }
            fout.write(json.dumps(doc) + "\n")
            fout.flush()

            tot = time.perf_counter() - t_phase
            avg = tot / i
            eta = avg * (len(pending) - i)
            active_gb = mx.get_active_memory() / 1e9
            peak_gb = mx.get_peak_memory() / 1e9
            print(
                f"[{i:>4d}/{len(pending)}] {pdf_path.name:<46s} "
                f"pages={len(page_texts)} wall={wall_seconds:6.1f}s "
                f"({wall_seconds / max(len(page_texts), 1):5.1f}s/pg) "
                f"mem={active_gb:.1f}/{peak_gb:.1f}GB "
                f"elapsed={tot / 60:6.1f}min eta={eta / 60:6.1f}min"
            )

    elapsed = time.perf_counter() - t_phase
    print()
    print(
        f"Done. {len(pending)} PDFs / {n_pages_total} pages in {elapsed:.1f}s "
        f"({elapsed / 60:.1f}min)"
    )
    if errored:
        print(f"\n{len(errored)} errored PDF(s) (first 5):")
        for p, e in errored[:5]:
            print(f"  {p}: {e}")
    return out_jsonl


def main() -> None:
    # Line-buffer stdout so a hard abort (e.g. a Metal watchdog crash)
    # still leaves the progress log on disk up to the failing page.
    sys.stdout.reconfigure(line_buffering=True)

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"MLX model repo (default: {DEFAULT_MODEL})",
    )
    p.add_argument(
        "--corpus-root",
        type=Path,
        default=None,
        help="Materialized corpus root (default: platformdirs user cache)",
    )
    p.add_argument(
        "--workspace",
        type=Path,
        default=None,
        help="Working dir for page renders + dolma JSONL "
        "(default: <corpus-root>/../olmocr_mlx_workspace)",
    )
    p.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Output benchmark-row JSONL path",
    )
    p.add_argument(
        "--sources",
        type=int,
        default=None,
        help="Limit to the first N source_ids (×7 variants). Omit for the full 700.",
    )
    p.add_argument("--image-dim", type=int, default=DEFAULT_IMAGE_DIM)
    p.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    p.add_argument(
        "--no-resume",
        action="store_true",
        help="Ignore (and overwrite) any existing workspace JSONL.",
    )
    args = p.parse_args()

    corpus_root = args.corpus_root or default_corpus_cache_dir()
    # Materialize the corpus if it isn't already on disk.
    ensure_corpus(cache_dir=corpus_root)

    workspace = args.workspace or (corpus_root.parent / "olmocr_mlx_workspace")
    workspace.mkdir(parents=True, exist_ok=True)

    run_olmocr_mlx(
        corpus_root=corpus_root,
        workspace=workspace,
        model_name=args.model,
        image_dim=args.image_dim,
        max_tokens=args.max_tokens,
        source_limit=args.sources,
        resume=not args.no_resume,
    )

    # Score the dolma docs against ground truth → benchmark rows.
    rows = import_olmocr_workspace(
        workspace=workspace,
        corpus_root=corpus_root,
        out_jsonl=args.out,
        strict=False,
    )
    print(f"\nWrote {len(rows)} benchmark rows -> {args.out}")
    errored = sum(1 for r in rows if r["error"])
    if errored:
        print(f"  ({errored} rows carry an error)", file=sys.stderr)


if __name__ == "__main__":
    main()
