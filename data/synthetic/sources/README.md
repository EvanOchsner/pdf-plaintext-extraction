# Synthetic gold-set source corpus

Each `.txt` file in this directory is a plain-text source passage. It is
the ground truth for the synthetic-benchmark accuracy score: a rendered
clean PDF (in `../clean/`) and its poisoned variants (in `../poisoned/`)
are constructed deterministically from this text, so any extractor's
output can be compared back to it directly.

## Categories present

- `gutenberg-*` — public-domain text from Project Gutenberg, used as a
  domain-neutral control. Any extractor failure on these is purely about
  PDF structure, not insurance-specific vocabulary.
- `md-insurance-*` — passages from the Maryland Insurance Code
  (Title 27 of the Annotated Code of Maryland). Authoritative plain
  text, published by the Maryland General Assembly.
- `naic-model-*` — passages from NAIC Model Laws, the industry-standard
  templates that many state codes derive from.

## Adding new sources

1. Drop a UTF-8 text file in this directory. Filename = source ID
   (no spaces).
2. Rebuild the clean PDF: `python -m scripts.synthesize.clean_pdf
   --source <path> --out ../clean/<id>.pdf`.
3. Apply poisoning techniques: see `../../scripts/synthesize/poison.py`
   when that lands.
4. Refresh the ground-truth manifest: `python -m
   scripts.synthesize.ground_truth`.

## Important: this seed corpus is small on purpose

The five starter files committed here are short, hand-curated passages
intended for first-cut harness validation. The full synthetic benchmark
will be ~30 sources × ~10 poisoning variants = ~300 PDFs once the
acquisition of authoritative source text is automated by
`sources_fetch.py`.
