# Obfuscation taxonomy

Working taxonomy of "PDF poisoning" techniques the fingerprinter
(`scripts/obfuscation/`) detects per document. Each entry describes:

- **Definition** — what the technique is structurally.
- **Effect** — how it degrades downstream text extraction.
- **Detection signal** — what to look for in the PDF object stream / fonts
  to identify it without rendering or OCRing the page.
- **Severity for extraction** — rough expectation of how badly it breaks
  pdftotext-class extractors.

This is the v0 list. Expand as the obfuscation cataloger surfaces patterns
not anticipated here.

## 1. No text layer (image-only)

- **Definition.** Page content stream contains only image XObjects; no
  text-showing operators (`Tj`, `TJ`, `'`, `"`).
- **Effect.** pdftotext / pypdf return empty string. OCR is required.
- **Detection signal.** Walk content stream; count text-showing operators
  per page. Zero → image-only.
- **Severity.** High for naive extractors; moderate for OCR-equipped.

## 2. Custom-encoded fonts (broken / missing ToUnicode)

- **Definition.** Font is embedded with a custom encoding whose CMap
  either has no `/ToUnicode` stream or maps glyphs to nonsense Unicode
  (e.g. private-use area, scrambled).
- **Effect.** Text layer exists and extracts as visually-meaningless
  Unicode sequences. Renders correctly visually.
- **Detection signal.** Inspect font dictionaries; flag any font missing
  `/ToUnicode`, or where the `/ToUnicode` mapping decodes a known English
  word to a non-word.
- **Severity.** Catastrophic for all text-layer extractors; OCR works fine.

## 3. CID-without-ToUnicode

- **Definition.** Variant of (2) using a CID-keyed font with no
  `/ToUnicode` mapping back to characters.
- **Effect.** Same as (2).
- **Detection signal.** Type0 / CIDFontType subtype + no `/ToUnicode`.

## 4. Invisible / off-page text

- **Definition.** Text drawn with rendering mode 3 (`Tr 3`), zero text
  matrix scale, or position outside `/MediaBox`.
- **Effect.** Either hides intended text from view but leaves it in the
  extract (poisoning the extract), or hides real text from extractors
  while showing only an image overlay.
- **Detection signal.** Scan content stream for `Tr 3` operators, zero-
  scale text matrices, or text-showing operators at positions outside the
  mediabox.

## 5. Watermarks

- **Definition.** Repeated text/image overlay on every (or most) pages.
- **Effect.** Watermark text leaks into extracted text on every page,
  polluting downstream analysis.
- **Detection signal.** Per-page-recurring text strings; or `/Watermark`
  annotations.

## 6. Header/footer noise

- **Definition.** Recurring per-page strings that are not body content
  (page numbers, filer IDs, "Confidential — Draft").
- **Effect.** Same pollution pattern as (5), at lower severity.
- **Detection signal.** Strings appearing at the top or bottom of every
  page.

## 7. Form fields (AcroForm / XFA)

- **Definition.** Document is or contains a fillable form. May be
  flattened (text baked in) or live (text in `/V` field values, not in
  content stream).
- **Effect.** Naive extractors miss field values entirely.
- **Detection signal.** Presence of `/AcroForm` or `/XFA` in document
  catalog; field-value strings absent from page content streams.

## 8. Encrypted / password-protected

- **Definition.** `/Encrypt` dictionary present.
- **Effect.** Extractors that don't handle encryption fail outright.
- **Detection signal.** `/Encrypt` in trailer.

## 9. Text-under-image / image-over-text

- **Definition.** Page draws both a text layer and a covering image; the
  visible image differs from the underlying text.
- **Effect.** Extracted text and rendered text disagree — extraction
  silently returns wrong content.
- **Detection signal.** OCR the rendered page; compare to extracted text
  layer. Disagreement above a threshold = positive.

## 10. Homoglyph substitution

- **Definition.** Visually-Latin characters drawn with Cyrillic / Greek /
  full-width Unicode codepoints (e.g. Cyrillic `а` U+0430 in place of
  Latin `a` U+0061).
- **Effect.** String search / regex / LLM tokenization breaks; OCR
  recovers correct Latin.
- **Detection signal.** Codepoint distribution per page — any non-Latin
  codepoint embedded in otherwise-Latin words.

## 11. Character-spacing obfuscation

- **Definition.** Text rendered with large `Tc` (character spacing) or
  positioned glyph-by-glyph via `TJ` with large advances, so the text
  layer reads as "h e l l o" instead of "hello".
- **Effect.** Word boundaries lost; downstream NLP fails.
- **Detection signal.** Median inter-glyph advance vs. font's intrinsic
  width; ratio > threshold.

## 12. Non-standard PDF producers

- **Definition.** Document's `/Producer` or `/Creator` metadata is a
  known scan-to-PDF pipeline or known-bad converter.
- **Effect.** Indirect — a heuristic prior on extraction quality, not a
  poisoning technique per se.
- **Detection signal.** Producer-string matching against a tracked list.
