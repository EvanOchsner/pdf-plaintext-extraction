# Finding 02 — Synthetic-benchmark results (n=100)

**Date:** 2026-05-19
**Status:** Production-scale results. Synthetic gold set is 100 sources
× 7 variants = 700 PDFs. Cloud vision LLMs (Claude, Gemini) wired but
skipped this run pending API budget. Six local extractors compared
(pypdf, pdfplumber, pdftotext, Tesseract, Docling, PAT cascade).
OlmOCR-2 (open vision LLM) added 2026-05-20 on a 10-source subset —
see the OlmOCR-2 section.

This supersedes the n=3 preliminary writeup that previously occupied
this file. **Important revision:** an earlier finding that "PAT's
garble-detection escalation doesn't fire on rasterize" was a small-
sample artifact at n=3. At n=100 PAT escalates correctly and scores
0.986 on rasterize. See "Implications for the PAT cascade" below.

## What got measured

End-to-end run of the W5 benchmark harness against the W4 synthetic
gold set, scored by token-level F1 vs. the source text.

- **6 PDF text extractors** ran on every variant of every source:
  pypdf, pdfplumber, pdftotext (poppler), Tesseract OCR (via pypdfium2 +
  pytesseract), Docling (2.94, with built-in RapidOCR fallback), and
  the PAT cascade (subprocess-invoked from the sibling repo). Claude
  vision and Gemini vision wrappers are present but produced
  graceful-skip rows pending API keys.
- **7 PDF variants per source:** clean baseline plus six obfuscation
  techniques applied independently — `watermark`, `metadata_swap`,
  `rasterize`, `homoglyph`, `char_spacing`, `invisible_text`.
- **100 source texts** balanced ~20 per pool:
  - `gutenberg` — Project Gutenberg literary excerpts (pre-1930 PD).
  - `federal-register` — federal rules/notices via the Federal
    Register API; 17 distinct agencies (EPA, FDA, FCC, FTC, SEC, NRC,
    OSHA, FAA, IRS, CMS, NHTSA, CPSC, FWS, FedReserve, DHS, USCIS,
    USDA).
  - `usc` — United States Code sections from uscode.house.gov; 16
    distinct titles (7, 11, 12, 15, 17, 18, 19, 21, 22, 26, 29, 33,
    38, 42, 47, 50).
  - `wikipedia` — English Wikipedia article extracts via the
    MediaWiki API; science / history / geography / engineering.
  - `agency-pubs` — federal-agency factsheets (CDC pinkbook chapters,
    NIH NINDS overviews, NIST/NOAA/USGS/EPA/FDA/Treasury/Fed/USDA).

All sources are public-domain or CC-BY-SA-compatible. Curation,
deduplication, and SHA-256 manifests live in
`pdf_plaintext_extraction/data/sources/` (committed) and
`_provenance.jsonl`.

## Sample preparation

Per-source excerpts target ~1500 words / 3-5 rendered pages. Mean is
**4.8 pages** per clean PDF.

The renderer (reportlab + DejaVu Sans, see
`pdf_plaintext_extraction/synthesize/clean_pdf.py`) restricts the input
to Latin-script + standard punctuation by replacing non-Latin
codepoints (CJK, Cyrillic, Greek, Arabic, Hebrew, etc.) with `?` at
source-write time. This is deliberate: the v1 dataset measures
extraction quality on Latin-script content; future iterations can
disentangle "extraction quality" from "non-Latin script handling"
by adding pools with Unicode-aware fonts and bidirectional renderers.

Round-trip exactness on the clean PDFs:
- **95/100** byte-exact match (source.txt → clean PDF → pypdf →
  normalize == source.txt → normalize).
- **100/100** score token-F1 ≥ 0.99 vs. source.
- The 5 non-exact cases all share the same cause: Federal Register
  documents containing very long URLs that reportlab's `Paragraph`
  widget can't fit on one line and breaks mid-token, inserting a
  single space character that pypdf reads back literally. Damage per
  affected source is exactly one extra space token (F1 loss ≈ 0.001).

## Results

Mean token F1 per (extractor × variant), averaged over the 100 sources:

| extractor    | char_spacing |  clean   | homoglyph | invisible_text | metadata_swap | rasterize | watermark |
|--------------|-------------:|---------:|----------:|---------------:|--------------:|----------:|----------:|
| pat-cascade  |    **1.000** |  **1.000** | **0.986** |      **0.999** |     **1.000** | **0.986** | **0.995** |
| pypdf        |        1.000 |   1.000  |     0.497 |          0.999 |         1.000 |     0.000 |     0.995 |
| pdfplumber   |        0.010 |   1.000  |     0.497 |          0.999 |         1.000 |     0.000 |     0.965 |
| pdftotext    |        0.017 |   0.998  |     0.496 |          0.997 |         0.998 |     0.000 |     0.976 |
| docling      |        0.016 |   0.986  |     0.489 |          0.985 |         0.986 |     0.840 |     0.981 |
| tesseract    |        0.085 |   0.986  |     0.986 |          0.986 |         0.986 |     0.986 |     0.849 |

Each cell is the mean over 100 sources. Bold = column-leader at three
decimal places. Claude vision and Gemini vision returned graceful-skip
rows (700 each) because API keys aren't set in this run.

A seventh extractor — **OlmOCR-2**, an open vision LLM — was run
separately on a 10-source subset (it can't share this n=100 table yet);
see [OlmOCR-2 (vision LLM) — n=10 subset](#olmocr-2-vision-llm--n10-subset)
below.

**Per-pool variation** is small. On the `clean` column, every text-layer
tool hits 1.000 ± 0.006 across all five pools (`gutenberg`,
`federal-register`, `usc`, `wikipedia`, `agency-pubs`). On the
`rasterize` column, PAT and Tesseract recover 0.97–0.99 uniformly
across pools; Docling drops to 0.79–0.87 with usc the lowest (statute
formatting confuses RapidOCR's line detector more than narrative
prose).

Raw results JSONL: `experiments/results/synthetic_20260519T050436.jsonl`
(written incrementally — see `pdf_plaintext_extraction/benchmark/run_synthetic.py`).
Reproducible end-to-end with
`uv run python -m pdf_plaintext_extraction.benchmark.run_synthetic`.

## Observations

**1. The harness control passes for every text-layer extractor.**
pypdf, pdfplumber, and pat-cascade hit 1.000 on the clean column;
pdftotext lands at 0.998. The 0.986 for both Tesseract and Docling
reflects systematic OCR / markdown-serialization noise, not extraction
failure. Per-pool numbers are tight (1.000 ± 0.006 for text-layer
tools across all five pools), so any other-column failure is a real
extraction effect, not a content artifact.

**2. PAT cascade wins or ties every column except `clean`.**
PAT alone scores ≥ 0.986 on every variant, including the two that
defeat every other extractor (rasterize, homoglyph). On the seven
columns combined it averages **0.995**, vs. 0.713 for pypdf, 0.640
for pdftotext / pdfplumber, 0.755 for docling, and 0.842 for
tesseract. Cascade design is paying off.

**3. Tesseract is the only single-pass extractor that defeats both
rasterize and homoglyph.** Tesseract scores 0.986 on both because
OCR sees rendered pixels, not the underlying codepoints — Cyrillic
homoglyphs visually identical to Latin get re-recognized as Latin,
and rasterized PDFs are exactly what OCR is built for. The trade-off
shows up on `watermark` (0.849) and `char_spacing` (0.085): noise
from the watermark text gets OCRed into the output, and wide
inter-character gaps confuse the line / word segmenter.

**4. Docling sits between Tesseract and the text-layer tools.**
Built-in RapidOCR fallback gives Docling 0.840 on rasterize — better
than the 0.000 of pure text-layer tools, worse than Tesseract's
0.986 because Docling's markdown post-processing introduces more
serialization noise. Docling is the easiest "drop-in everything"
choice when you don't want to maintain a cascade, but a cascade that
explicitly invokes Tesseract on tier-0 failure beats it on every
column except `watermark` and `invisible_text` (where the difference
is < 0.02).

**5. `char_spacing` cleanly splits text-layer extractors into two
camps.** pypdf and pat-cascade score 1.000 because pypdf reconstructs
words from glyph positions and ignores the Tc spacing operator.
pdftotext (0.017), pdfplumber (0.010), docling (0.016), and tesseract
(0.085) all read the wide gaps as word boundaries and emit `h e l l o`
output. This is a capability test where pypdf wins by a wide margin —
a meaningful finding for anyone choosing an extractor for documents
with abnormal kerning.

**6. `metadata_swap` is invisible to all extractors (all ≥ 0.986),
but visible to the W3 fingerprinter at 100%.** Pure-text extraction
ignores the docinfo / XMP metadata, which is why every extractor's
score on this column matches its clean-column score. The
fingerprinter's job is exactly to catch obfuscations that hide from
text extraction — and it does, with 100% precision on this technique.

**7. `invisible_text` barely moves token F1 (0.985–0.999).** The
synthetic payload is one ~70-character invisible-rendering-mode
overlay; in a 1500-word excerpt that's < 2% of token count, so even
when extractors pick it up the F1 only drops by 0.001–0.014.
Real-world invisible-text attacks would need to be substantially
larger to materially affect benchmark scores. Worth tracking when
the real-document corpus lands.

## OlmOCR-2 (vision LLM) — n=10 subset

[Allen AI's OlmOCR-2](https://github.com/allenai/olmocr) (a
Qwen2.5-VL-7B fine-tune) is the benchmark's first vision-LLM
extractor. Unlike the six text-layer / OCR tools above, OlmOCR
rasterizes each page and reads it as an image through a 7B
vision-language model — so it is structurally immune to text-layer
codepoint tricks and behaves like an OCR tool with a language model's
reconstruction ability.

**Run setup.** OlmOCR's upstream inference path is vLLM + CUDA, which
runs on neither Apple Silicon nor a free Kaggle T4 (vLLM/torch ABI
breakage; `bitsandbytes` ships no Turing-`sm75` kernel). It runs
locally on Apple Silicon instead via MLX —
`mlx-community/olmOCR-2-7B-1025-8bit` (an 8-bit quant of the same
model, within ~0.5% of bf16) through `mlx-vlm`, driven by
`pdf_plaintext_extraction.benchmark.olmocr_mlx`. At ~74 s/page on an
M2 the full 700-PDF corpus is a ~66 h run, so this is a **10-source
subset** (10 sources × 7 variants = 70 PDFs, 399 page-inferences,
8.2 h wall). The numbers below are directional — not yet
1:1-comparable with the n=100 columns above.

Mean token F1 and per-PDF / per-page wall time, over the 10 sources
(run 2026-05-20, M2, 8-bit MLX):

| variant | n | mean F1 | mean NED | s / PDF | s / page |
|---|---:|---:|---:|---:|---:|
| `clean` (none) | 10 | 0.990 | 0.016 | 472.4 | 82.9 |
| `watermark` | 10 | 0.984 | 0.023 | 431.0 | 75.6 |
| `metadata_swap` | 10 | 0.990 | 0.016 | 426.4 | 74.8 |
| `rasterize` | 10 | 0.989 | 0.018 | 433.6 | 76.1 |
| `homoglyph` | 10 | 0.990 | 0.016 | 428.9 | 75.2 |
| `char_spacing` | 10 | 0.618 | 0.547 | 351.6 | 61.7 |
| `invisible_text` | 10 | 0.990 | 0.016 | 421.1 | 73.9 |
| **poisoned (all 6)** | 60 | 0.927 | 0.106 | 415.4 | 72.9 |

Artifact: `experiments/results/olmocr_mlx_n10.jsonl` (70 rows, standard
benchmark schema, `extractor: "olmocr"`).

**Observations.**

1. **OlmOCR defeats every pixel-invariant technique.** rasterize
   (0.989), homoglyph (0.990), and invisible_text (0.990) all sit at
   the clean baseline (0.990). A vision model only ever sees rendered
   pixels: a rasterized page is its native input; Cyrillic homoglyphs
   render as Latin-looking glyphs and are read back as Latin; and
   invisible-rendering-mode text is, by definition, not on the page the
   model sees. This is the same profile as Tesseract (all three
   ≈ 0.986) — both are pixel-based — with OlmOCR a hair higher on the
   clean control (a 0.004 gap at n=10, i.e. within noise).

2. **`char_spacing` is OlmOCR's one real weakness (0.618).** Wide
   inter-character kerning makes the model read `h e l l o` as separate
   tokens — the same failure mode that sinks Tesseract (0.085),
   pdftotext (0.017), and Docling (0.016). OlmOCR's 0.618 is far better
   than those — the language model partially reconstructs words from
   context — but nowhere near pypdf / pat-cascade's 1.000, which win
   this column by ignoring the Tc operator and reconstructing from
   glyph positions. A vision LLM has no glyph-position channel to fall
   back on.

3. **`watermark` (0.984) and `metadata_swap` (0.990) behave as
   expected.** metadata_swap touches only docinfo / XMP, invisible to
   any text or vision extractor, so it sits at the clean score.
   watermark dips slightly because the overlay text is visually present
   and bleeds into the extraction — same direction as Tesseract's
   watermark dip, milder here.

4. **Runtime tracks page count, not technique.** Per-page wall is a
   tight 74–83 s for every variant except char_spacing. char_spacing is
   the *fastest* (61.7 s/page) precisely because the model emits less /
   more-fragmented text and stops sooner; `clean` is the slowest
   (82.9 s/page) — it has the most genuine text to transcribe. The
   "none" vs "all-methods" split: clean averages 472.4 s/PDF, the
   six-technique poisoned aggregate 415.4 s/PDF. On an M2, OlmOCR runs
   ~10,000× slower per page than pypdf (≈0.008 s/page) — four orders of
   magnitude. Its accuracy on pixel-invariant attacks is bought with a
   very large compute bill.

**Bottom line.** OlmOCR is, with Tesseract, one of only two extractors
that beats both `rasterize` and `homoglyph` — and it edges Tesseract on
the clean control and clearly beats it on `char_spacing` (0.618 vs
0.085). But it does not displace the PAT cascade: PAT scores ≥ 0.986 on
*every* column, including `char_spacing` at 1.000 where OlmOCR collapses
to 0.618. OlmOCR's niche is documents that are purely image-based or
codepoint-poisoned — at a compute cost four orders of magnitude above
the text-layer tools. Scaling this column to the full n=100 (a ~66 h
M2 run, or a CUDA host where vLLM works) is tracked in Next steps.

## Obfuscation prevalence (W3 fingerprinter)

Mean signal-trip rate by variant, across the 700-PDF corpus
(`data/obfuscation_fingerprints.jsonl`):

| variant | n | pages | no-text | invis | tc>3 | wm | non-Latin | susp-prod |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| clean | 100 | 4.8 | 0% | 0% | 0% | 0.05 | 0.000 | 0% |
| watermark | 100 | 4.8 | 0% | 0% | 0% | **1.00** | 0.000 | 0% |
| metadata_swap | 100 | 4.8 | 0% | 0% | 0% | 0.05 | 0.000 | **100%** |
| rasterize | 100 | 4.8 | **100%** | 0% | 0% | 0.00 | 0.000 | 0% |
| homoglyph | 100 | 4.8 | 0% | 0% | 0% | 0.01 | **0.112** | 0% |
| char_spacing | 100 | 4.8 | 0% | 0% | **100%** | 0.05 | 0.000 | 0% |
| invisible_text | 100 | 4.8 | 0% | **100%** | 0% | 0.05 | 0.000 | 0% |

Each technique's dedicated signal trips at 100% (homoglyph's non-Latin
ratio is 0.112 because the synthetic substitution replaces ~1/3 of
eligible Latin letters; the ratio reports the fraction of all
codepoints that ended up non-Latin). A small base rate of
`watermark_score = 0.05` on the clean column reflects FR documents
whose first-page mastheads ("DEPARTMENT OF..." etc.) match the
heuristic's "all-caps recurring header" pattern. Easy to refine but
doesn't muddy the actual watermark signal which trips ~20× stronger.

## Implications for the PAT cascade

**PAT outperforms Docling on every dimension that matters.** Across
the seven variants, PAT averages 0.995 vs. Docling 0.755. The two
columns where Docling is close (rasterize 0.840 vs PAT 0.986; clean
0.986 vs PAT 1.000) are exactly where Docling's "all-in-one" pitch
would matter most — and PAT's tier-3 Tesseract backstop wins them.

**The remaining headroom for PAT is `homoglyph` and `watermark`.**
PAT scores 0.986 on homoglyph (matches Tesseract), 0.995 on watermark.
The gap to a hypothetical perfect extractor is small. Concretely:
- On homoglyph PAT relies on Tesseract's pixel-OCR. Any post-processing
  to detect-and-correct homoglyph substitution at the text-layer stage
  (e.g., flag non-Latin-in-Latin-context codepoints, re-extract via
  OCR) could push to 1.000 without paying full OCR cost on every page.
- On watermark PAT inherits pypdf's 0.995. The watermark text leaks
  into the body; an explicit watermark-removal post-process (W3
  detects the watermark already) could subtract those tokens.

**For the SERFF case study, PAT is the right benchmark anchor.**
When real MD-SERFF data becomes available, comparing against PAT's
column will be the highest-information comparison.

## What this still can't tell us

- **No frontier vision LLM numbers.** Claude vision and Gemini vision
  wrappers are wired up; running them is a matter of setting
  `ANTHROPIC_API_KEY` / `GOOGLE_API_KEY`. Cost estimate: ~$20 for a
  full pass over the 700-PDF synthetic set.
- **No real-corpus data.** SERFF acquisition remains blocked under
  the ToS finding (see [01-serff-tos-review.md](01-serff-tos-review.md)).
  Real-document numbers wait on hand collection per
  [docs/hand-collection-guide.md](../hand-collection-guide.md) or a
  sanctioned NAIC/MIA channel.
- **Latin-script only.** This run measures extraction on Latin-script
  content; non-Latin scripts (Cyrillic / Greek / Arabic / Hebrew /
  CJK) were substituted out of sources during fetch. A multi-script
  follow-up needs a Unicode-aware renderer and bidirectional layout.

## Next steps in priority order

1. Run cloud-LLM extractors (Claude vision + Gemini vision) on the
   same 700-PDF corpus once API budget approved.
2. Scale the OlmOCR-2 column from n=10 to the full n=100 — either a
   ~66 h unattended M2 run (`olmocr_mlx`, resumable) or a CUDA host
   where vLLM works — so it shares the main results table.
3. Add a 6th pool focused on non-Latin scripts (CJK, Arabic, etc.)
   with a Unicode-capable renderer; measure how OCR-based extractors
   vs. text-layer extractors handle the script split.
4. Hand-collect the SERFF pilot (~30 filings) and run the same
   fingerprinter + benchmark against real disclosures.
5. File any PAT-cascade tickets surfaced by the n=100 comparison.
