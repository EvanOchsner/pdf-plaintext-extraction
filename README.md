# pdf-plaintext-extraction

[![CI](https://github.com/EvanOchsner/pdf-plaintext-extraction/actions/workflows/ci.yml/badge.svg)](https://github.com/EvanOchsner/pdf-plaintext-extraction/actions/workflows/ci.yml)

An academic benchmark and obfuscation taxonomy for PDF text extraction.
Measures how "PDF poisoning" techniques — watermarks, homoglyph
substitution, abnormal character spacing, rasterization, invisible
text, scrambled font CMaps — degrade common extraction tools, and
tracks which techniques appear in real-world publicly-disclosed
documents.

**Status:** pre-alpha. Synthetic-benchmark harness operational
end-to-end against six local extractors (pypdf, pdfplumber, pdftotext,
Tesseract, Docling, PAT cascade); Claude vision and Gemini vision
wrappers wired but pending API keys. Real-corpus collection in
progress as an applied case study, not the main thrust.

## Why

PDFs that look ordinary on screen often resist automated parsing.
Some of this is incidental (the PDF spec is permissive about how
glyphs map to characters), but some of it is deliberate — adversarial
patterns that defeat OCR, LLM-based extraction, and traditional text
layer readers while remaining visually identical to a human reader.

This project asks three connected questions:

1. **What does PDF poisoning look like?** A taxonomy of twelve
   structural techniques, with per-technique detection signals that
   run cheaply over any PDF.
   ([docs/obfuscation-taxonomy.md](docs/obfuscation-taxonomy.md))
2. **How badly does it break each common tool?** A reproducible
   synthetic benchmark with byte-exact ground truth that scores every
   extractor on every technique.
   ([docs/findings/02-synthetic-benchmark-preliminary.md](docs/findings/02-synthetic-benchmark-preliminary.md))
3. **How often do these techniques appear in the wild?** A prevalence
   study over real corpora (case study: Maryland SERFF insurance
   filings — see [Applied case studies](#applied-case-studies)).

## What's inside

- **Obfuscation fingerprinter** ([scripts/obfuscation/](scripts/obfuscation/))
  — static-analysis pass over any PDF emitting a per-technique fingerprint
  (image-only, missing-ToUnicode fonts, invisible-text pages, watermark
  score, homoglyph ratio, abnormal Tc values, suspicious producer
  string, AcroForm/XFA, encryption).
- **Synthetic gold-set generator** ([scripts/synthesize/](scripts/synthesize/))
  — fetches public-domain source text, renders deterministic clean PDFs
  (`Canvas(invariant=1)` — byte-identical re-renders), applies each of
  six poisoning techniques to produce ground-truth-anchored variants.
  Techniques: `watermark`, `metadata_swap`, `rasterize`, `homoglyph`,
  `char_spacing`, `invisible_text`.
- **Benchmark harness** ([scripts/benchmark/](scripts/benchmark/))
  — uniform `Extractor` protocol with eight wrappers (pypdf, pdfplumber,
  pdftotext, Tesseract via pypdfium2, Docling, Claude vision, Gemini
  vision, [PAT cascade](https://github.com/EvanOchsner/personal-advocacy-toolkit)),
  token-F1 + normalized-edit-distance scorer, end-to-end run script.

## Getting started

### Prerequisites

- Python 3.11+ (tested on 3.13)
- [uv](https://docs.astral.sh/uv/) for dep management

System tools, all optional — extractors that depend on them error
gracefully when absent:

- `pdftotext` (poppler) for the `pdftotext` extractor
- `tesseract` for OCR-based extractors

On macOS: `brew install poppler tesseract`. On Debian/Ubuntu:
`apt install poppler-utils tesseract-ocr`.

### Install

```sh
git clone https://github.com/EvanOchsner/pdf-plaintext-extraction.git
cd pdf-plaintext-extraction
uv sync                          # core deps only
uv sync --extra benchmark        # + pdfplumber, pytesseract, Docling
uv sync --extra frontier         # + anthropic, google-generativeai
```

### Run the synthetic benchmark end-to-end

```sh
# 1. Fetch source text (small public-domain Gutenberg excerpts)
uv run python -m scripts.synthesize.sources_fetch --pool gutenberg

# 2. Render the clean control PDFs from each source
for src in data/synthetic/sources/*.txt; do
  id=$(basename "$src" .txt)
  uv run python -m scripts.synthesize.clean_pdf \
    --source "$src" --out "data/synthetic/clean/$id.pdf"
done

# 3. Apply every poisoning technique to every source
uv run python -m scripts.synthesize.poison --all

# 4. Build the ground-truth manifest
uv run python -m scripts.synthesize.ground_truth

# 5. Run the benchmark (all extractors; cloud LLMs skip without keys)
uv run python -m scripts.benchmark.run_synthetic
```

The benchmark prints a mean-F1 table per (extractor × variant) and
writes a per-row JSONL to `experiments/results/`. The clean column is
the harness control: every extractor should score near-perfect on it.
Anything that fails the control points to a wrapper bug, not a
poisoning effect.

### Run the obfuscation fingerprinter on a corpus

```sh
uv run python -m scripts.obfuscation.fingerprint \
  --pdf-glob 'data/synthetic/**/*.pdf' \
  --out data/obfuscation_fingerprints.jsonl
```

Single-document mode prints the fingerprint to stdout:

```sh
uv run python -m scripts.obfuscation.fingerprint --pdf path/to/file.pdf
```

### Enable cloud vision LLMs

```sh
export ANTHROPIC_API_KEY=...     # Claude Sonnet 4.6 vision
export GOOGLE_API_KEY=...        # Gemini 2.0 Flash
uv run python -m scripts.benchmark.run_synthetic
```

Cost estimate: $1–$3 for a full pass over the current synthetic set.

### Run the tests

```sh
uv run pytest
```

24 tests covering the renderer's determinism, ground-truth
round-tripping, each poisoning technique's structural signal, the
fingerprinter's per-technique detection, and the scorer's metric
correctness.

## Layout

```
pdf-plaintext-extraction/
├── data/
│   ├── synthetic/
│   │   ├── sources/                 # plain-text inputs (committed)
│   │   ├── clean/                   # clean PDFs (gitignored, regenerable)
│   │   ├── poisoned/<technique>/    # one subdir per technique (gitignored)
│   │   └── ground_truth.jsonl       # (gitignored, regenerable)
│   └── obfuscation_fingerprints.jsonl  # (gitignored)
├── scripts/
│   ├── obfuscation/    # W3 — fingerprinter
│   ├── synthesize/     # W4 — clean render + poisoning
│   ├── benchmark/      # W5 — extractor wrappers + scorer + runner
│   ├── acquire/        # (placeholder for corpus acquisition adapters)
│   └── normalize/      # (placeholder for manifest builder)
├── docs/
│   ├── obfuscation-taxonomy.md
│   ├── hand-collection-guide.md
│   └── findings/
├── tests/
└── experiments/
    └── results/         # benchmark JSONL output (gitignored)
```

## Applied case studies

The benchmark is target-agnostic — any corpus of PDFs works. The
project's motivating case study is Maryland SERFF (the public-access
portal for state insurance rate-and-form filings):

- [docs/findings/01-serff-tos-review.md](docs/findings/01-serff-tos-review.md)
  — why we cannot automate downloads from SERFF and the options for
  sanctioned acquisition.
- [docs/hand-collection-guide.md](docs/hand-collection-guide.md) —
  step-by-step instructions for compliantly pulling a pilot sample
  through the SERFF web interface.

Other corpora (FOIA-released government PDFs, carrier-published
consumer documents, public court records) plug into the same
pipeline: the fingerprinter and benchmark take any PDF as input and
don't depend on SERFF specifics.

## Licensing

This repo is dual-licensed:

- **Code** under MIT — see [LICENSE-CODE](LICENSE-CODE). Covers
  `scripts/`, `tests/`, `pyproject.toml`.
- **Dataset and documentation** under CC-BY-4.0 — see
  [LICENSE-DATA](LICENSE-DATA). Covers `data/`, `docs/`.

## Companion project

The [Personal Advocacy Toolkit](https://github.com/EvanOchsner/personal-advocacy-toolkit)
(PAT) consumes the findings of this project to improve its extraction
cascade. PAT's `cascade.py` is one of the eight benchmarked extractors.
