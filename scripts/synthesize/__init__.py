"""W4: synthetic gold-truth benchmark set.

The synthetic set is constructed from authoritative plain-text sources
(insurance statutes, NAIC model laws, public-domain materials) rendered
into deterministic clean PDFs, then poisoned with the techniques from
the PDF-Poisoning library. Because the source text is the ground truth
by construction, this set anchors the benchmark's accuracy numbers.

Pipeline:

    sources_fetch.py   -> data/synthetic/sources/<id>.txt
    clean_pdf.py       -> data/synthetic/clean/<id>.pdf
    poison.py          -> data/synthetic/poisoned/<technique>/<id>.pdf
    ground_truth.py    -> data/synthetic/ground_truth.jsonl
"""
