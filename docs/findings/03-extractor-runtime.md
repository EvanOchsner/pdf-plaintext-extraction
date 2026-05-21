# Finding 03 — Extractor runtime on the n=10 subset

**Date:** 2026-05-20
**Status:** Complete. All seven benchmarked extractors timed on a fixed
10-source subset (10 sources × 7 variants = 70 PDFs, 399 page renders)
so per-method throughput is directly comparable. Six text-layer / OCR
extractors timed in a dedicated run; OlmOCR-2 from the 2026-05-20 MLX
run.

## Why a separate timing finding

Finding 02 measures *accuracy* (token-F1). It reports OlmOCR-2's wall
time because that was a deliberate, isolated measurement — but the six
other extractors' per-PDF times in the n=100 results JSONL were recorded
incidentally, interleaved with each other under unknown machine load.
This finding re-times all seven on one fixed subset, one extractor at a
time, on the same machine — so a claim like "OlmOCR is N× slower than
pypdf" is a defensible number rather than an artifact of scheduling.

## What got measured

- **Subset:** the first 10 source_ids (sorted) — the identical set
  OlmOCR-2 ran in finding 02:
  `cdc-dpdx-malaria`, `cdc-pinkbook-flu`, `cdc-pinkbook-mmr`,
  `epa-lead`, `epa-radon`, `fda-allergens`, `fda-radiation`,
  `fed-discount-window`, `fr-2024-16138`, `fr-2024-30293`.
- **70 PDFs** (10 sources × 7 variants), **399 page renders**.
- **Wall time** per (extractor × PDF) — `wall_seconds` from the harness
  `timed()` wrapper.
- **Machine:** Apple M2, 16 GB. Extractors run sequentially per PDF, so
  there is no cross-extractor CPU contention within a measurement. No
  extractor errored — all six ran on all 70 PDFs.

Commands:

```sh
# Six text-layer / OCR extractors on the n=10 subset.
uv run python -m pdf_plaintext_extraction.benchmark.run_synthetic \
    --sources 10 \
    --extractors pypdf,pdfplumber,pdftotext,tesseract,docling,pat-cascade \
    --out experiments/results/timing_n10.jsonl

# OlmOCR-2 via MLX (finding 02):
#   experiments/results/olmocr_mlx_n10.jsonl
```

## Results — mean wall time per extractor

Mean over the 70 PDFs; `s/page` divides total wall by the 399 page
renders. Ordered fastest first.

| extractor | backend | mean s/PDF | mean s/page | × vs pypdf |
|---|---|---:|---:|---:|
| pypdf | text-layer | 0.017 | 0.003 | 1× |
| pdftotext | text-layer (poppler) | 0.062 | 0.011 | 3.5× |
| pdfplumber | text-layer | 0.177 | 0.031 | 10× |
| pat-cascade | tiered (text → OCR) | 3.74 | 0.656 | 214× |
| tesseract | OCR (pixel) | 6.67 | 1.170 | 383× |
| docling | OCR + layout | 13.23 | 2.320 | 759× |
| **olmocr** | vision LLM (MLX) | **423.6** | **74.3** | **~24,300×** |

The whole six-extractor timing run took ~28 min of extraction wall;
OlmOCR-2 alone took 8.2 h on the same 70 PDFs.

## Results — per-variant wall time (mean s/PDF)

| extractor | clean | watermark | metadata_swap | rasterize | homoglyph | char_spacing | invisible_text |
|---|---:|---:|---:|---:|---:|---:|---:|
| pypdf | 0.023 | 0.025 | 0.018 | 0.004 | 0.015 | 0.016 | 0.022 |
| pdftotext | 0.098 | 0.048 | 0.053 | 0.051 | 0.058 | 0.069 | 0.054 |
| pdfplumber | 0.172 | 0.293 | 0.198 | 0.004 | 0.169 | 0.220 | 0.182 |
| pat-cascade | 0.234 | 0.213 | 0.265 | 4.566 | 20.353 | 0.246 | 0.284 |
| tesseract | 6.086 | 5.766 | 5.753 | 5.916 | 5.698 | 11.690 | 5.785 |
| docling | 7.107 | 6.156 | 5.143 | 53.598 | 4.545 | 8.668 | 7.370 |
| **olmocr** | 472.4 | 431.0 | 426.4 | 433.6 | 428.9 | 351.6 | 421.1 |

## Observations

**1. Three cost tiers spanning four-plus orders of magnitude.**
Text-layer parsers (pypdf / pdftotext / pdfplumber) sit at
0.003–0.031 s/page — they only walk the content stream, nothing is
rendered. OCR tools (tesseract, docling) are 1.2–2.3 s/page — they
rasterize then recognize every page. OlmOCR-2 is 74 s/page: a 7B vision
model doing autoregressive decoding. End to end, OlmOCR is ~24,300×
slower per PDF than pypdf.

**2. Among text-layer tools, pypdf is fastest; pdfplumber pays ~10× for
its layout model.** pdftotext (poppler's C implementation) lands in
between at 3.5×. All three are still sub-0.2 s/PDF — the choice between
them is about accuracy and API, not speed.

**3. pat-cascade's adaptive cost is visible in its per-variant row.**
It runs ~0.21–0.27 s on the five variants whose text layer is usable
(clean, watermark, metadata_swap, char_spacing, invisible_text) — i.e.
text-layer speed — but spikes to **4.57 s on rasterize** and **20.35 s
on homoglyph**, the two variants where the text layer is unusable and
the cascade escalates to OCR. Its 3.74 s/PDF mean is almost entirely
those two cells. This is the cascade design working as intended: pay OCR
cost only when garble-detection trips. (Finding 02: pat-cascade still
scores ≥ 0.99 on every variant.)

**4. docling's worst case is rasterize (53.6 s — ~7× its other
variants).** RapidOCR on a full-page raster with no text-layer hints is
where docling is slowest. tesseract is far more uniform (~5.7–6.1 s)
except `char_spacing` (11.7 s, ~2×), where wide inter-character gaps
roughly double the segmenter's work.

**5. OlmOCR-2's fastest variant is char_spacing (351.6 s).** A vision
LLM's wall time scales with tokens generated; on char_spacing the model
emits less / more-fragmented text and stops sooner. `clean` is its
slowest (472.4 s) — the most genuine text to transcribe. See finding 02
for the accuracy side.

**6. The runtime ÷ accuracy trade-off.** Pairing this with finding 02:
pypdf extracts a PDF in 3 ms/page but scores **0.000** on `rasterize`;
OlmOCR-2 scores **0.989** on `rasterize` but costs 74 s/page —
~24,000× more. pat-cascade is the pragmatic middle: text-layer speed
(~0.2 s/PDF) on clean documents, escalating to OCR cost only on the
poisoned variants, for ≥ 0.99 accuracy across the board at a 3.74 s/PDF
blended mean.

## Cross-reference

Accuracy (token-F1) for the same extractors and subset is in
[02-synthetic-benchmark-preliminary.md](02-synthetic-benchmark-preliminary.md).
Raw timing rows: `experiments/results/timing_n10.jsonl` (6 extractors)
and `experiments/results/olmocr_mlx_n10.jsonl` (OlmOCR-2).
