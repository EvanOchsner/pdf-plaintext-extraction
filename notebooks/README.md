# Notebooks

End-to-end runnable notebooks that document and reproduce specific
benchmark runs. Each notebook is self-contained: it locates (or clones)
the repo, materializes the corpus, runs the experiment, and emits a
JSONL artifact in the standard benchmark row schema.

## `olmocr_benchmark.ipynb` — OlmOCR column, platform-adaptive

Adds Allen AI's [OlmOCR-2](https://github.com/allenai/olmocr)
(Qwen2.5-VL-7B fine-tune) to the synthetic benchmark. OlmOCR is a
vision LLM — it rasterizes each page and reads it as an image — so it
needs a GPU. The notebook **detects its accelerator and dispatches**:

| Platform | Backend | Status |
|---|---|---|
| NVIDIA CUDA GPU | vLLM offline `LLM` | best-effort |
| Apple Silicon (M-series) | MLX via `mlx-vlm` | **validated path** |
| CPU only | — | stops with a message |

Both GPU backends emit identical dolma-doc JSONL into a workspace
directory; `pdf_plaintext_extraction.benchmark.olmocr_importer` scores
it against ground truth and writes rows with `extractor: "olmocr"`.

Set `SOURCE_LIMIT` in Phase 0 to subset the corpus (`10` → 10 sources
× 7 variants = 70 PDFs; `None` → full 700).

### Apple Silicon (validated)

OlmOCR's upstream path is vLLM + CUDA, which does not exist on a Mac.
The Apple-Silicon path runs the same model through Apple's MLX/Metal
stack instead — `mlx-community/olmOCR-2-7B-1025-8bit` via `mlx-vlm`.

For a long run, prefer the module directly over the notebook — it is
resumable, frees the Metal buffer cache between pages (avoids the GPU
watchdog timeout on memory-constrained Macs), and prints ETA:

```sh
uv sync --extra ocr-mlx
uv run python -m pdf_plaintext_extraction.benchmark.olmocr_mlx \
    --sources 10 \
    --out experiments/results/olmocr_mlx_n10.jsonl
```

`--sources N` limits to the first N source_ids; omit it for the full
700-PDF corpus. The run is resumable — re-running skips PDFs already in
the workspace. Expected throughput: ~74 s/page on an M2 (8-bit), so the
full corpus is ~66 h; a 10-source subset is ~8 h.

The notebook's `mlx` branch calls the same `run_olmocr_mlx()` function.

### CUDA (Kaggle / Colab / any CUDA host)

1. Open the notebook in Kaggle (Settings → Accelerator → GPU) or Colab
   (Runtime → T4 GPU).
2. **Run All.** The `cuda` branch installs vLLM, loads the model with
   `dtype="float16"` (T4-friendly) and a 16 GB-safe `max_model_len`,
   and runs `LLM.chat` over base64 page images.
3. Download the `olmocr_rows.jsonl` artifact from `/kaggle/working/`.

Note: vLLM's prebuilt wheels are sensitive to the host's exact
torch/CUDA ABI. On a host where the pinned `vllm==0.11.2` does not load,
adjust the pin in Phase 2 to match the platform's torch.

### Merging the artifact into the benchmark

`olmocr_rows.jsonl` is in the standard row schema, keyed on
`(extractor, source_id, variant)`. A full-corpus run merges directly:

```sh
cat olmocr_rows.jsonl >> experiments/results/synthetic_<timestamp>.jsonl
```

A subset run (`SOURCE_LIMIT` set) produces a partial column — keep it
as its own artifact rather than merging, and report it separately. See
[docs/findings/02-synthetic-benchmark-preliminary.md](../docs/findings/02-synthetic-benchmark-preliminary.md)
for the n=10 OlmOCR results already recorded.

### Why isn't OlmOCR a normal `Extractor` wrapper?

The benchmark's `Extractor` protocol expects a per-PDF Python callable
on any platform. OlmOCR needs a GPU and a ~30 s model load; treating it
as a separate notebook / module-driven run keeps the local benchmark
harness CPU-only and dependency-light, while `olmocr_importer.py` pipes
the output back into the standard row schema.
