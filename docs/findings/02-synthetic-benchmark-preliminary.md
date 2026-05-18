# Finding 02 — Preliminary synthetic-benchmark results

**Date:** 2026-05-18
**Status:** Preliminary. Synthetic gold set only (3 sources × 7 variants
= 21 PDFs). Real MD-SERFF corpus not yet acquired (see
[01-serff-tos-review.md](01-serff-tos-review.md) for why). Cloud vision
LLMs (Claude, Gemini) wired but not yet exercised — API keys pending.

## What got measured

A first end-to-end run of the W5 benchmark harness against the W4
synthetic gold set, scored by token-level F1 against the source text:

- **6 PDF text extractors** ran on every variant of every source:
  pypdf, pdfplumber, pdftotext (poppler), Tesseract OCR, Docling, and
  the PAT cascade. Claude vision and Gemini vision are wired up but
  produced graceful-skip rows pending API keys.
- **7 PDF variants per source:** the unmodified clean baseline plus
  six obfuscation techniques applied independently (watermark,
  metadata_swap, rasterize, homoglyph, char_spacing, invisible_text).
- **3 source texts:** short Project Gutenberg excerpts (Alice's
  Adventures, Pride and Prejudice, Moby-Dick chapter openings).
  Domain-neutral on purpose — they isolate the obfuscation effect from
  any insurance-vocabulary effect.

## Results

Mean token F1 per (extractor × variant), averaged over the 3 sources:

| extractor     | char_spacing |  clean | homoglyph | invisible_text | metadata_swap | rasterize | watermark |
|---------------|-------------:|-------:|----------:|---------------:|--------------:|----------:|----------:|
| docling       |        0.023 |  0.949 |     0.555 |          0.946 |         0.949 | **0.831** |     0.946 |
| pat-cascade   |        1.000 |  1.000 |     0.584 |          0.996 |         1.000 |     0.000 |     0.996 |
| pdfplumber    |        0.013 |  1.000 |     0.584 |          0.996 |         1.000 |     0.000 |     0.974 |
| pdftotext     |        0.022 |  1.000 |     0.584 |          0.996 |         1.000 |     0.000 |     0.983 |
| pypdf         |    **1.000** |  1.000 |     0.584 |          0.996 |         1.000 |     0.000 |     0.996 |
| tesseract     |        0.118 |  0.983 | **0.982** |          0.983 |         0.983 | **0.983** |     0.872 |

Raw results: [experiments/results/synthetic_20260518T124247.jsonl](../../experiments/results/synthetic_20260518T124247.jsonl).
Reproducible end-to-end with `uv run python -m scripts.benchmark.run_synthetic`.

## Observations

**The clean column is the harness control.** Every extractor scores
≥0.949 on the un-poisoned baseline. The 0.949 for Docling reflects
markdown-style formatting Docling adds (bullets, heading marks)
that introduces tiny token differences vs. raw plaintext, not actual
errors. This confirms the harness itself isn't biasing results: any
"failure" elsewhere in the table is a real extraction failure, not
a measurement artifact.

**Tesseract is the only extractor that recovers from rasterization.**
On the `rasterize` column every text-layer extractor scores 0.000 —
the PDF has no text layer, so there's nothing to extract. Tesseract
scores 0.983 because it runs OCR on the page images. Docling lands
between them at 0.831 because it has a built-in OCR fallback
(RapidOCR), but its layout post-processing introduces more noise
than vanilla Tesseract. **This is the headline argument for a
cascade design:** when the cheap text-layer methods return empty,
the expensive OCR path has to take over.

**Tesseract is also the only extractor that defeats homoglyph
substitution.** Homoglyph replaces every third Latin letter with its
Cyrillic lookalike — visually identical, byte-different. Every
text-layer extractor scores 0.584 because the Cyrillic codepoints
flow straight from the PDF text stream into the output, breaking
token comparison. Tesseract sees pixels, not codepoints, and OCRs the
glyphs back to Latin — 0.982. This is a real finding for the
prevalence study: homoglyph attacks defeat every text-layer tool
uniformly, and OCR is the only escape.

**`char_spacing` cleanly splits the text-layer extractors.** pypdf
and pat-cascade (which wraps pypdf at tier 0) score 1.000 because
pypdf reconstructs words from glyph positions and ignores the wide
inter-character gaps. pdftotext, pdfplumber, and Docling score
0.013–0.023 because they interpret the abnormal Tc operator as
literal word boundaries and emit `h e l l o` style output. This is
a meaningful capability difference that wouldn't have surfaced
without a controlled synthetic input.

**`invisible_text` barely moves the needle (0.946–0.996).** The
synthetic implementation adds one ~70-character invisible payload
at the bottom of the last page. Token F1 is dominated by the
hundreds of correctly-extracted body tokens; the payload contributes
a few tokens of noise. Real-world invisible-text attacks would need
to be much larger to materially affect scores — worth keeping in
mind when the real-SERFF prevalence numbers land.

**`metadata_swap` is invisible to text extraction (all 1.000).**
The W3 fingerprinter catches it 100% of the time, but it has no
effect on extracted text — as expected. Useful as a control that
our other measurements aren't picking up confounding signals.

## Implications for PAT

Two concrete pieces of feedback for the
[PAT extraction cascade](https://github.com/EvanOchsner/personal-advocacy-toolkit/tree/main/scripts/extraction):

1. **PAT's garble-detection escalation didn't fire on the
   rasterized synthetic PDFs.** The cascade returned an empty
   tier-0 (pypdf) result without escalating to tier-3 (Tesseract),
   scoring 0.000 on `rasterize`. PAT *can* do OCR — the cascade just
   didn't trigger it. Worth checking whether the garble heuristic
   treats "no text at all" as garbled, or whether it needs at least
   one character to score.
2. **Docling beats PAT on rasterize without needing a cascade.**
   Docling 2.94 ships built-in OCR fallback via RapidOCR. If PAT
   adopted Docling as its tier-1, rasterized PDFs would be handled
   automatically; the explicit tier-2/tier-3 escalation could be
   reserved for the harder cases (custom-mapped fonts, char_spacing
   abuse) where Docling itself fails.

## What this can't tell us yet

- **No frontier vision LLM numbers.** Claude vision and Gemini
  vision wrappers are wired up; running them is a matter of setting
  `ANTHROPIC_API_KEY` / `GOOGLE_API_KEY`. Cost estimate: $1–$3 for a
  full pass over the current 21-PDF synthetic set.
- **No real-corpus data.** The legal block on SERFF scraping (see
  [finding 01](01-serff-tos-review.md)) means the real-MD-SERFF
  prevalence numbers wait on hand collection per
  [docs/hand-collection-guide.md](../hand-collection-guide.md), or
  on a sanctioned bulk channel via NAIC/MIA.
- **Three sources is a small sample.** Inter-source variance hasn't
  been measured; the per-cell F1 numbers above are means over n=3.
  A handful of additional Gutenberg sources would tighten the
  numbers without any new infrastructure.

## Next steps in priority order

1. Add 10–20 more Gutenberg / MD-statute / NAIC-model-law sources to
   make the synthetic F1 numbers stable (n=20 instead of n=3).
2. Run the cloud-LLM extractors with API keys for a head-to-head
   against the open-source baselines.
3. Hand-collect the SERFF pilot (~30 filings) and re-run the
   benchmark + fingerprinter on real disclosures.
4. File the PAT garble-escalation issue based on (1) above.
