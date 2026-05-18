# serff-extraction

A curated academic dataset of insurance filings from the Maryland SERFF public
access portal, plus a benchmark of common PDF text-extraction tools against
the obfuscation ("PDF poisoning") techniques present in those documents.

**Status:** pre-alpha. Synthetic-benchmark harness end-to-end against 6
local extractors (frontier vision LLMs wired but unrun). Real-corpus
acquisition deferred pending SERFF ToS resolution — see findings below.

## Findings so far

- [01 — SERFF ToS prohibits automated download](docs/findings/01-serff-tos-review.md):
  the original polite-scraper plan is blocked; hand-collection or a
  sanctioned NAIC/MIA channel are the open paths.
- [02 — Preliminary synthetic-benchmark results](docs/findings/02-synthetic-benchmark-preliminary.md):
  first per-extractor / per-poisoning-technique F1 table. Tesseract is
  the only tool that recovers from rasterization or homoglyph attacks;
  pypdf is unusually robust to char-spacing abuse; Docling is a strong
  single-tool generalist via built-in OCR fallback.

## Why

The Maryland Insurance Administration requires carriers to publicly disclose
rate filings and policy forms via the [SERFF public access portal](https://filingaccess.serff.com/sfa/home/MD).
These documents are nominally "open" — any member of the public can fetch them
— but in practice many are distributed as PDFs that resist automated parsing:
image-only scans, custom-mapped fonts, invisible text layers, watermarks, and
other patterns that degrade OCR, LLM, and traditional extractor output.

This project:

1. Acquires and curates a stratified sample of MD SERFF PDFs as a reproducible
   academic dataset.
2. Catalogs the prevalence of obfuscation techniques across the corpus.
3. Benchmarks open-source extractors (pdftotext, pypdf, pdfplumber, Tesseract,
   Docling, olmocr), frontier vision LLMs (Claude, Gemini), and the
   [PAT](https://github.com/EvanOchsner/personal-advocacy-toolkit) extraction
   cascade against the corpus and a synthetic ground-truth set.

## Layout

```
data/
  manifest.jsonl                  # one row per real-SERFF PDF
  obfuscation_fingerprints.jsonl  # per-doc obfuscation taxonomy fingerprint
  synthetic/                      # synthetic adversarial benchmark
    sources/                      # plain-text source corpora (statutes, etc.)
    clean/                        # un-poisoned rendered PDFs
    poisoned/                     # poisoned variants, one subdir per technique
    ground_truth.jsonl

scripts/
  acquire/      # SERFF portal scraper
  normalize/    # manifest, dedup, dataset publish
  obfuscation/  # static fingerprinter
  synthesize/   # clean PDF render + PDF-Poisoning application
  benchmark/    # extractor wrappers + scorer

experiments/    # configs + results
docs/           # taxonomy notes + findings writeups
```

## Licensing

This repo is dual-licensed:

- **Code** under MIT — see [LICENSE-CODE](LICENSE-CODE). Covers `scripts/`,
  `tests/`, `pyproject.toml`, and any other source code.
- **Dataset and documentation** under CC-BY-4.0 — see [LICENSE-DATA](LICENSE-DATA).
  Covers `data/`, `docs/`, and any aggregate findings.

Whether the SERFF PDFs themselves can be redistributed alongside the manifest
depends on the outcome of the in-progress SERFF ToS review. If redistribution
is not permitted, this repo ships the manifest + acquisition scripts only and
end users reacquire the PDFs from SERFF directly.

## Companion project

The [Personal Advocacy Toolkit](https://github.com/EvanOchsner/personal-advocacy-toolkit)
(PAT) is the downstream consumer of this dataset — improvements to its
extraction cascade are the primary motivation for building the benchmark here.
