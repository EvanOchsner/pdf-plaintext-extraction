"""W3: obfuscation cataloger.

Static analysis pass over PDFs that emits a fingerprint of which
poisoning techniques are present, per the taxonomy in
``docs/obfuscation-taxonomy.md``.

Designed to run without rendering or OCRing pages — the cheap path
that lets us catalog hundreds of documents quickly. Where a definitive
signal needs OCR (e.g. text-under-image disagreement), the field is
marked ``"unknown"`` and a heavier downstream pass can resolve it.
"""
