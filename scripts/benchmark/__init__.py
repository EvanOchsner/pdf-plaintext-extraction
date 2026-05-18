"""W5: extraction benchmark harness.

Runs a uniform set of PDF text extractors against a corpus and scores
each one against ground-truth (for the synthetic set) or against
inter-method agreement (for any real corpus, which has no ground
truth).

Each extractor implements ``scripts.benchmark.base.Extractor``:

    extract(pdf_path) -> ExtractionResult

Wrappers shipped in this package:

- ``pypdf_extractor``      — pypdf high-level text extraction (already a dep)
- ``pdfplumber_extractor`` — pdfplumber (in [benchmark] extras)
- ``pdftotext_subproc``    — poppler's pdftotext CLI (external tool)

Wrappers to add in follow-up turns:

- Tesseract (rasterize + OCR)
- Docling
- olmocr
- Claude vision
- Gemini vision
- PAT cascade
"""
