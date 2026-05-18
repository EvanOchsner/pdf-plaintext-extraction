"""Fetch authoritative plain-text sources for the synthetic gold set.

Two source pools, both public-domain or open-license:

1. **Project Gutenberg** — domain-neutral control corpus. We pull a few
   short, paragraph-sized excerpts from clearly-public-domain texts via
   the Gutenberg plain-text mirror. Excerpts are clipped to a few
   hundred words so each rendered PDF stays at ~1–3 pages.

2. **Maryland General Assembly statute pages** — for in-domain coverage,
   fetched from the MGA's public statute portal as HTML and converted
   to plain text. The statute text itself is uncopyrightable government
   work product.

A third pool (NAIC model laws) is intentionally deferred: NAIC distributes
those as PDFs/Word documents, not plain text, and they may carry their own
distribution restrictions. We'll add them after a license check.

Each fetched source is written as a UTF-8 ``.txt`` file under
``data/synthetic/sources/``. A small ``_provenance.jsonl`` is appended
alongside, recording the source URL, fetch timestamp, and SHA-256 so the
seed corpus is reproducible.

Usage:

    python -m scripts.synthesize.sources_fetch --pool gutenberg
    python -m scripts.synthesize.sources_fetch --pool md-statute
    python -m scripts.synthesize.sources_fetch --pool all
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
SOURCES_DIR = ROOT / "data" / "synthetic" / "sources"
PROVENANCE_PATH = SOURCES_DIR / "_provenance.jsonl"

UA = "pdf-plaintext-extraction/0.0.1 (academic research; +https://github.com/EvanOchsner/pdf-plaintext-extraction)"

# A small set of clearly-public-domain Project Gutenberg texts. Each entry
# names a Gutenberg ID and an excerpt window so we get a paragraph-sized
# passage rather than the whole book. The texts here are not insurance-
# adjacent on purpose — they serve as a domain-neutral control.
# skip_marker_occurrences=N starts the excerpt after the (N+1)-th occurrence
# of the marker — useful for skipping table-of-contents entries that repeat
# the chapter header before the actual chapter body begins.
GUTENBERG_EXCERPTS = [
    {
        "source_id": "gutenberg-pg11-ch1",
        "gutenberg_id": 11,  # Alice's Adventures in Wonderland
        "url": "https://www.gutenberg.org/cache/epub/11/pg11.txt",
        "after_marker": "CHAPTER I.",
        "skip_marker_occurrences": 1,
        "max_chars": 3000,
    },
    {
        "source_id": "gutenberg-pg1342-ch1",
        "gutenberg_id": 1342,  # Pride and Prejudice
        "url": "https://www.gutenberg.org/cache/epub/1342/pg1342.txt",
        "after_marker": "Chapter I.",
        "skip_marker_occurrences": 1,
        "max_chars": 3000,
    },
    {
        "source_id": "gutenberg-pg2701-ch1",
        "gutenberg_id": 2701,  # Moby Dick
        "url": "https://www.gutenberg.org/cache/epub/2701/pg2701.txt",
        "after_marker": "CHAPTER 1.",
        "skip_marker_occurrences": 1,
        "max_chars": 3000,
    },
]


@dataclass
class ProvenanceRow:
    source_id: str
    pool: str
    url: str
    fetched_iso: str
    bytes_written: int
    sha256: str
    notes: str = ""


def _http_get(url: str, *, timeout: float = 30.0) -> str:
    with httpx.Client(headers={"User-Agent": UA}, timeout=timeout, follow_redirects=True) as c:
        r = c.get(url)
        r.raise_for_status()
        return r.text


def _strip_gutenberg_header(text: str) -> str:
    start_re = re.compile(r"\*\*\* START OF (THE |THIS )?PROJECT GUTENBERG.*?\*\*\*", re.IGNORECASE)
    end_re = re.compile(r"\*\*\* END OF (THE |THIS )?PROJECT GUTENBERG.*?\*\*\*", re.IGNORECASE)
    m_start = start_re.search(text)
    m_end = end_re.search(text)
    if m_start:
        text = text[m_start.end() :]
    if m_end:
        text = text[: m_end.start()]
    return text.strip()


def _slice_excerpt(
    text: str, after_marker: str, max_chars: int, skip_marker_occurrences: int = 0
) -> str:
    idx = -1
    search_from = 0
    for _ in range(skip_marker_occurrences + 1):
        idx = text.find(after_marker, search_from)
        if idx == -1:
            break
        search_from = idx + len(after_marker)
    body = text[idx:] if idx != -1 else text
    body = body[:max_chars]
    last_break = body.rfind("\n\n")
    if last_break > max_chars // 2:
        body = body[:last_break]
    return body.strip()


def _write_source(source_id: str, content: str, pool: str, url: str) -> ProvenanceRow:
    SOURCES_DIR.mkdir(parents=True, exist_ok=True)
    out_path = SOURCES_DIR / f"{source_id}.txt"
    out_path.write_text(content, encoding="utf-8")
    data = out_path.read_bytes()
    row = ProvenanceRow(
        source_id=source_id,
        pool=pool,
        url=url,
        fetched_iso=dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        bytes_written=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )
    _append_provenance(row)
    return row


def _append_provenance(row: ProvenanceRow) -> None:
    PROVENANCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with PROVENANCE_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(asdict(row)) + "\n")


def fetch_gutenberg() -> list[ProvenanceRow]:
    rows = []
    for spec in GUTENBERG_EXCERPTS:
        raw = _http_get(spec["url"])
        body = _strip_gutenberg_header(raw)
        excerpt = _slice_excerpt(
            body,
            spec["after_marker"],
            spec["max_chars"],
            skip_marker_occurrences=spec.get("skip_marker_occurrences", 0),
        )
        if not excerpt:
            raise RuntimeError(f"no excerpt produced for {spec['source_id']}")
        rows.append(_write_source(spec["source_id"], excerpt, "gutenberg", spec["url"]))
    return rows


def fetch_md_statute(_urls: list[str] | None = None) -> list[ProvenanceRow]:
    """Placeholder. The MGA statute portal serves statute pages as HTML;
    deciding which sections to pull is a curation decision the user
    makes. Until those URLs are decided, this returns an empty list and
    the gutenberg pool alone seeds the corpus.
    """
    return []


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--pool", choices=["gutenberg", "md-statute", "all"], default="all")
    args = p.parse_args()

    rows: list[ProvenanceRow] = []
    if args.pool in ("gutenberg", "all"):
        rows.extend(fetch_gutenberg())
    if args.pool in ("md-statute", "all"):
        rows.extend(fetch_md_statute())

    print(f"wrote {len(rows)} source(s) to {SOURCES_DIR.relative_to(ROOT)}")
    for r in rows:
        print(f"  {r.source_id:35s} {r.bytes_written:6d} bytes  {r.sha256[:12]}…")


if __name__ == "__main__":
    main()
