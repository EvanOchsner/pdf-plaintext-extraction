# White paper — Extracting Plaintext from Adversarial PDFs

LaTeX source for the project's pre-print: a synthetic benchmark of PDF
plaintext extractors against six obfuscation techniques.

## Build

Requires a TeX distribution with **XeLaTeX** and `latexmk` (TeX Live or
MacTeX). From this directory:

```sh
latexmk        # -> main.pdf
latexmk -c     # remove aux files
```

`latexmkrc` pins the engine to XeLaTeX and runs BibTeX automatically.

## Figures

The six obfuscation figures pair a rendered page ("what a human sees")
with a naive extractor's output ("what the machine gets"). Both are
generated assets, committed under `figures/`:

| asset | meaning |
|---|---|
| `figures/<variant>_page.png` | page 1 rendered at 150 DPI |
| `figures/<variant>_extracted.txt` | curated extractor-output snippet |

Only three page renders are distinct (`clean`, `watermark`,
`char_spacing`); the other four techniques leave the page
pixel-identical to the clean document — that visual invisibility *is*
the attack — so the paper reuses `clean_page.png` for them.

### Regenerating

`figures/make_figures.py` rebuilds every asset from the benchmark
corpus. It needs the `pdf-plaintext-extraction` package and a
materialized corpus (it calls `ensure_corpus()` if one is absent). Run
from the repo root:

```sh
uv run python paper/figures/make_figures.py
```

The representative source document is `fr-2024-16138` (a Federal
Register rule, part of the n=10 timing subset).

## Data sources

All results are transcribed from the project findings docs:

- `docs/findings/02-synthetic-benchmark-preliminary.md` — token-F1
  accuracy (n=100) and the OlmOCR-2 n=10 subset.
- `docs/findings/03-extractor-runtime.md` — runtime (n=10 subset).
- `docs/obfuscation-taxonomy.md` — the obfuscation taxonomy.
