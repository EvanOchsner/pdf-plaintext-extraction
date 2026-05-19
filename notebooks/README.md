# Notebooks

End-to-end runnable notebooks that document and reproduce specific
benchmark runs. Each notebook is self-contained: it clones the repo at
its current commit, materializes the corpus, runs the experiment, and
emits a JSONL artifact in the standard benchmark row schema.

## `olmocr_benchmark.ipynb` — OlmOCR column on a free CUDA GPU

Adds Allen AI's [OlmOCR](https://github.com/allenai/olmocr) (Qwen2-VL-
based) to the synthetic benchmark. The OlmOCR inference path requires
CUDA (vLLM), so this notebook offloads the heavy work to a free GPU
runtime — Kaggle T4 by default, Colab T4 as a fallback. The artifact it
produces (700 rows in the standard schema) merges directly into the
local benchmark JSONL.

### Running on Kaggle (recommended)

1. Open https://www.kaggle.com/code → **New notebook** → **File → Import notebook** and upload
   `olmocr_benchmark.ipynb`.
2. In the right sidebar: **Settings → Accelerator → GPU T4 × 1**. Free
   tier has a 30 hr/week GPU quota; this run uses ~1 hr.
3. **Save & Run All (Commit)**. The notebook runs detached and survives
   browser closure. Outputs land at `/kaggle/working/` and are captured
   with the commit.
4. After the commit finishes, the output JSONL is downloadable:
   - Web UI: open the committed notebook → **Output** tab → download
     `olmocr_rows.jsonl`.
   - CLI: `kaggle kernels output <kaggle-user>/<notebook-slug>`.

Expected wall time: 30–90 min (T4, single-worker vLLM, 700 PDFs averaging
~5 pages each).

### Running on Colab (fallback)

1. Open https://colab.research.google.com → **File → Upload notebook**.
2. **Runtime → Change runtime type → T4 GPU**.
3. **Runtime → Run all**. Outputs land in the Colab session filesystem;
   download via the file panel before the session disconnects.

Colab's free tier session limits are tighter than Kaggle's, but the
notebook fits in a single session.

### Running in VS Code with a remote kernel

1. Install the **Jupyter** + **Kaggle** (or equivalent) VS Code
   extension that exposes a remote-kernel selector.
2. Start a Kaggle / Colab session and copy the kernel URL into the VS
   Code kernel picker.
3. Open `notebooks/olmocr_benchmark.ipynb` in VS Code; cells execute on
   the remote GPU while you read/edit locally.

### Local follow-up after the artifact lands

```sh
# Append the 700 olmocr rows to the existing benchmark JSONL. `--resume`
# is keyed on (extractor, source_id, variant), so the merged JSONL drops
# in cleanly with the other 5,600 rows already there.
cat olmocr_rows.jsonl >> experiments/results/synthetic_20260519T050436.jsonl
```

Then update [docs/findings/02-synthetic-benchmark-preliminary.md](../docs/findings/02-synthetic-benchmark-preliminary.md)
with the OlmOCR row in the F1 table and the runtime stats from the
notebook's Phase 3 measurement.

### Reproducibility

The notebook prints a reproducibility marker in its final cell:

- `olmocr` package version
- model name (`allenai/olmOCR-2-7B-1025` BF16 by default; override at the
  top of Phase 2 if a newer release exists)
- GPU name + driver as detected by `torch.cuda`
- batch wall time

Any future re-run can compare against these markers. The corpus itself
is regenerated from the committed `pdf_plaintext_extraction/data/sources/*.txt`,
so the inputs are identical commit-to-commit.

### Why isn't OlmOCR a normal `Extractor` wrapper?

The benchmark's `Extractor` protocol expects a per-PDF Python callable.
OlmOCR is a vLLM batch pipeline — paying the ~30 s model-load on every
call is prohibitive, and vLLM doesn't run on Apple Silicon at all.
Treating it as a separate notebook-driven run keeps the local benchmark
harness simple (no CUDA dependency), while the `olmocr_importer.py`
module pipes the workspace output back into the standard row schema.
