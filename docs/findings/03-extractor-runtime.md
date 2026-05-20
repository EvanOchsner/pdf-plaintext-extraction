# Finding 03 — Extractor runtime on the n=10 subset

**Date:** 2026-05-20
**Status:** _In progress._ Timing the seven benchmarked extractors on a
fixed 10-source subset (10 sources × 7 variants = 70 PDFs, 399 page
renders) so per-method throughput is directly comparable. OlmOCR-2's row
is filled from the 2026-05-20 MLX run; the six text-layer / OCR
extractors are being timed in a dedicated run — cells marked `TBD`
until that job lands.

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
  there is no cross-extractor CPU contention within a measurement.

Commands:

```sh
# Six text-layer / OCR extractors on the n=10 subset.
uv run python -m pdf_plaintext_extraction.benchmark.run_synthetic \
    --sources 10 \
    --extractors pypdf,pdfplumber,pdftotext,tesseract,docling,pat-cascade \
    --out experiments/results/timing_n10.jsonl

# OlmOCR-2 via MLX (finding 02) — already produced:
#   experiments/results/olmocr_mlx_n10.jsonl
```

## Results — mean wall time per extractor

Mean over the 70 PDFs. `s/page` divides by the 399 page renders.

| extractor | backend | mean s/PDF | mean s/page | × vs pypdf |
|---|---|---:|---:|---:|
| pypdf | text-layer | TBD | TBD | 1× |
| pdfplumber | text-layer | TBD | TBD | TBD |
| pdftotext | text-layer (poppler) | TBD | TBD | TBD |
| pat-cascade | tiered (text → OCR) | TBD | TBD | TBD |
| tesseract | OCR (pixel) | TBD | TBD | TBD |
| docling | OCR + layout | TBD | TBD | TBD |
| **olmocr** | vision LLM (MLX) | **423.6** | **74.3** | TBD |

## Results — per-variant wall time (mean s/PDF)

| extractor | clean | watermark | metadata_swap | rasterize | homoglyph | char_spacing | invisible_text |
|---|---:|---:|---:|---:|---:|---:|---:|
| pypdf | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| pdfplumber | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| pdftotext | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| pat-cascade | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| tesseract | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| docling | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| **olmocr** | 472.4 | 431.0 | 426.4 | 433.6 | 428.9 | 351.6 | 421.1 |

## Observations

_To be written once the six-extractor timing job lands._ Expected
shape, to confirm or revise against the numbers:

- The three text-layer tools (pypdf / pdfplumber / pdftotext) should
  land in the millisecond-per-PDF range — they only parse the content
  stream, no rendering.
- tesseract and docling rasterize then OCR every page, so seconds per
  page; docling additionally runs layout analysis.
- pat-cascade is tiered: cheap when the text layer suffices, escalating
  to OCR only on a garble-detection trip — so its mean should sit
  between the text-layer tools and tesseract, and its per-variant row
  should spike exactly on `rasterize` (where escalation always fires).
- OlmOCR-2 is ~74 s/page — expected to be roughly four orders of
  magnitude above the text-layer tools.

## Cross-reference

Accuracy (token-F1) for the same extractors and subset is in
[02-synthetic-benchmark-preliminary.md](02-synthetic-benchmark-preliminary.md).
The runtime ÷ accuracy trade-off is the practical takeaway — e.g. pypdf
is orders of magnitude faster than OlmOCR but scores 0.000 on
`rasterize`, where OlmOCR scores 0.989.
