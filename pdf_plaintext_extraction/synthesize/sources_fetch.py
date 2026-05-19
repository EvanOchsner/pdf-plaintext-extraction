"""Fetch authoritative plain-text sources for the synthetic gold set.

The synthetic benchmark draws ground-truth source text from five
public-domain pools:

- **gutenberg** — pre-1930 literary works (PD by age) from Project
  Gutenberg's plain-text mirror. Domain-neutral control.
- **federal-register** — federal agency rules, proposed rules, and
  notices via the Federal Register JSON API. Federal works,
  17 USC § 105. (Substituted for the originally-planned courtlistener
  pool — CourtListener's API now requires authentication, while the
  Federal Register API is open and well-documented.)
- **usc** — sections of the United States Code from uscode.house.gov.
  Federal works, 17 USC § 105.
- **wikipedia** — English-Wikipedia article extracts via the MediaWiki
  ``extracts`` API. CC-BY-SA-licensed (compatible with this repo's
  CC-BY-4.0 dataset license under SA-compatible-attribution; full
  provenance recorded). Substituted for the originally-planned
  state-statute pool — state legislature sites varied wildly in
  scraping friendliness; Wikipedia adds an encyclopedic register
  without per-state fetcher complexity.
- **agency-pubs** — short federal agency fact sheets / reports
  (CDC / NIH / BLS / USGS). Federal works.

Each pool is a ``Pool`` instance with a list of ``PoolSpec`` rows and a
``fetch_one(spec) -> str`` callable that knows how to fetch + clean
that pool's documents. Every fetched source is written as a UTF-8
``.txt`` file into the package's ``data/sources/`` directory (which
ships inside the wheel). A ``_provenance.jsonl`` is appended alongside,
recording the source URL, fetch timestamp, and SHA-256 of the text bytes
so the seed corpus is reproducible. This module is a maintainer-only
tool — it requires an editable install (writes into the package tree).

Usage:

    python -m pdf_plaintext_extraction.synthesize.sources_fetch --pool gutenberg
    python -m pdf_plaintext_extraction.synthesize.sources_fetch --pool federal-register
    python -m pdf_plaintext_extraction.synthesize.sources_fetch --pool usc
    python -m pdf_plaintext_extraction.synthesize.sources_fetch --pool wikipedia
    python -m pdf_plaintext_extraction.synthesize.sources_fetch --pool agency-pubs
    python -m pdf_plaintext_extraction.synthesize.sources_fetch --pool all
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

import httpx

from pdf_plaintext_extraction._paths import package_sources_dir
from pdf_plaintext_extraction.synthesize._html import html_to_text

SOURCES_DIR = package_sources_dir()
PROVENANCE_PATH = SOURCES_DIR / "_provenance.jsonl"

UA = (
    "pdf-plaintext-extraction/0.0.1 (academic research; "
    "+https://github.com/EvanOchsner/pdf-plaintext-extraction)"
)

# Some federal-agency sites (NIH NINDS, CDC, others) bot-block any UA
# that isn't a real browser. We send a recent Chrome UA to those.
# The agency-pubs pool routes through this; other pools use the project
# UA where the server is fine with it.
CHROME_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# Minimum acceptable excerpt size after cleaning. An excerpt shorter
# than this almost always indicates a failed fetch or unexpected source
# layout — better to fail loudly so the curator updates the spec.
MIN_EXCERPT_WORDS = 500

# Target excerpt size: ~1500 words ≈ 9000 chars ≈ 3-5 rendered pages.
DEFAULT_MAX_CHARS = 10_000

# Codepoint ranges retained verbatim in source text. Everything outside
# these ranges is replaced with U+003F "?" at source-write time so the
# ground-truth text byte-aligns with what the renderer produces.
#
# Scope is intentionally Latin-script-only for the v1 dataset. The
# project pivots to multi-script benchmarking in a future iteration;
# disentangling "extraction quality" from "non-Latin script handling"
# lets v1 measure the former cleanly. Greek, Cyrillic, Arabic, Hebrew,
# CJK, Hangul, kana, and other non-Latin scripts are all replaced.
_RENDERABLE_RANGES: list[tuple[int, int]] = [
    (0x0009, 0x000A),  # tab, newline
    (0x000D, 0x000D),  # carriage return
    (0x0020, 0x007E),  # ASCII printable
    (0x00A0, 0x00FF),  # Latin-1 Supplement (à é ñ — common in English text)
    (0x0100, 0x017F),  # Latin Extended-A (č ł š ž — European diacritics)
    (0x0180, 0x024F),  # Latin Extended-B
    (0x1E00, 0x1EFF),  # Latin Extended Additional (Vietnamese, classical Latin)
    (0x2000, 0x206F),  # General Punctuation (em dash, curly quotes, ellipsis)
    (0x2070, 0x209F),  # Superscripts and Subscripts
    (0x20A0, 0x20CF),  # Currency Symbols
    (0x2100, 0x214F),  # Letterlike Symbols (™, ℅)
    (0x2150, 0x218F),  # Number Forms
    (0x2190, 0x21FF),  # Arrows
    (0x2200, 0x22FF),  # Mathematical Operators
    (0x2300, 0x23FF),  # Miscellaneous Technical
    (0x25A0, 0x25FF),  # Geometric Shapes
]

_RENDER_REPLACEMENT = "?"


def _is_renderable(cp: int) -> bool:
    return any(lo <= cp <= hi for lo, hi in _RENDERABLE_RANGES)


def _filter_to_renderable_charset(text: str) -> str:
    """Replace non-Latin codepoints with ``?``.

    Keeps text length stable so any line wrapping the renderer does will
    produce the same line breaks regardless of which chars are present.
    """
    return "".join(c if _is_renderable(ord(c)) else _RENDER_REPLACEMENT for c in text)


# Long runs of '=' or '-' are page-section separators in Federal Register
# plain-text dumps (and occasionally other federal sources). They aren't
# content; they break reportlab's Paragraph layout by being unbreakable
# tokens. Strip runs of 20+ identical separator chars; preserve short
# em-dash sequences and markdown-style horizontal rules.
_SEPARATOR_LINE = re.compile(r"[=\-]{20,}")


def _strip_separator_runs(text: str) -> str:
    return _SEPARATOR_LINE.sub("", text)


# -----------------------------------------------------------------------------
# Core dataclasses
# -----------------------------------------------------------------------------


@dataclass
class PoolSpec:
    """A single source entry within a pool.

    Required fields are ``source_id`` and ``url``. ``after_marker``,
    ``before_marker``, ``skip_marker_occurrences``, and ``max_chars`` are
    consumed by ``_slice_excerpt`` and pool-specific fetchers. ``extra``
    carries pool-specific knobs (e.g. a JSON path for the CourtListener
    body field).
    """

    source_id: str
    url: str
    after_marker: str | None = None
    before_marker: str | None = None
    skip_marker_occurrences: int = 0
    max_chars: int = DEFAULT_MAX_CHARS
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class Pool:
    """A named family of sources with a shared fetch/cleanup recipe.

    ``fetch_one(spec)`` returns the cleaned excerpt as a UTF-8 string
    (boilerplate stripped, sliced to roughly ``spec.max_chars``).
    """

    name: str
    specs: list[PoolSpec]
    fetch_one: Callable[[PoolSpec], str]


@dataclass
class ProvenanceRow:
    source_id: str
    pool: str
    url: str
    fetched_iso: str
    bytes_written: int
    sha256: str
    notes: str = ""


# -----------------------------------------------------------------------------
# HTTP + slicing primitives (reused across pools)
# -----------------------------------------------------------------------------


def _http_get(url: str, *, timeout: float = 30.0, user_agent: str = UA) -> str:
    """GET a URL. Raises on non-2xx. Defaults to the project UA;
    callers can override to a real-browser UA when a server bot-blocks
    library UAs."""
    with httpx.Client(
        headers={"User-Agent": user_agent}, timeout=timeout, follow_redirects=True
    ) as c:
        r = c.get(url)
        r.raise_for_status()
        return r.text


def _http_get_json(url: str, *, timeout: float = 30.0) -> Any:
    with httpx.Client(headers={"User-Agent": UA}, timeout=timeout, follow_redirects=True) as c:
        r = c.get(url)
        r.raise_for_status()
        return r.json()


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
    text: str,
    after_marker: str | None,
    max_chars: int,
    skip_marker_occurrences: int = 0,
    before_marker: str | None = None,
) -> str:
    """Slice an excerpt out of ``text`` deterministically.

    - If ``after_marker`` is given, start at its (skip+1)-th occurrence.
      The skip is useful when the marker appears in a TOC before the
      actual chapter/section body.
    - If ``before_marker`` is given, truncate the body at its first
      occurrence (whichever comes first: that, or ``max_chars``).
    - Walk back to the nearest paragraph boundary (``\\n\\n``) inside
      the second half of the excerpt so we don't cut a sentence mid-word.
    """
    # Anchor start
    idx = -1
    if after_marker:
        search_from = 0
        for _ in range(skip_marker_occurrences + 1):
            idx = text.find(after_marker, search_from)
            if idx == -1:
                break
            search_from = idx + len(after_marker)
    body = text[idx:] if idx != -1 else text

    # Anchor end (before_marker takes precedence over max_chars when found)
    if before_marker:
        end = body.find(before_marker)
        if end != -1:
            body = body[:end]

    body = body[:max_chars]
    last_break = body.rfind("\n\n")
    if last_break > max_chars // 2:
        body = body[:last_break]
    return body.strip()


# -----------------------------------------------------------------------------
# Provenance + write
# -----------------------------------------------------------------------------


def _write_source(source_id: str, content: str, pool: str, url: str) -> ProvenanceRow:
    SOURCES_DIR.mkdir(parents=True, exist_ok=True)
    out_path = SOURCES_DIR / f"{source_id}.txt"
    # Two normalizations before write so the ground truth aligns
    # byte-for-byte with what the synthetic-clean PDF will contain:
    #   1. Drop non-content separator runs (FR-style "======").
    #   2. Substitute non-Latin codepoints with "?" (v1 scope is
    #      Latin-script only; see ``_RENDERABLE_RANGES`` comment).
    content = _strip_separator_runs(content)
    content = _filter_to_renderable_charset(content)
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


def _validate_excerpt(spec: PoolSpec, excerpt: str) -> None:
    if not excerpt:
        raise RuntimeError(f"empty excerpt for {spec.source_id} ({spec.url})")
    n_words = len(excerpt.split())
    if n_words < MIN_EXCERPT_WORDS:
        raise RuntimeError(
            f"excerpt too short for {spec.source_id} ({spec.url}): "
            f"got {n_words} words, want >= {MIN_EXCERPT_WORDS}. "
            "Adjust spec.max_chars or markers."
        )


def _fetch_pool(pool: Pool) -> list[ProvenanceRow]:
    rows = []
    for spec in pool.specs:
        excerpt = pool.fetch_one(spec)
        _validate_excerpt(spec, excerpt)
        rows.append(_write_source(spec.source_id, excerpt, pool.name, spec.url))
    return rows


# -----------------------------------------------------------------------------
# Pool: gutenberg
# -----------------------------------------------------------------------------


def _fetch_gutenberg(spec: PoolSpec) -> str:
    raw = _http_get(spec.url)
    body = _strip_gutenberg_header(raw)
    return _slice_excerpt(
        body,
        spec.after_marker,
        spec.max_chars,
        skip_marker_occurrences=spec.skip_marker_occurrences,
        before_marker=spec.before_marker,
    )


GUTENBERG_SPECS: list[PoolSpec] = [
    PoolSpec(
        source_id="gutenberg-pg11-ch1",  # Alice's Adventures in Wonderland — Carroll
        url="https://www.gutenberg.org/cache/epub/11/pg11.txt",
        after_marker="CHAPTER I.",
        skip_marker_occurrences=1,
    ),
    PoolSpec(
        source_id="gutenberg-pg1342-ch1",  # Pride and Prejudice — Austen
        url="https://www.gutenberg.org/cache/epub/1342/pg1342.txt",
        after_marker="Chapter I.",
        skip_marker_occurrences=1,
    ),
    PoolSpec(
        source_id="gutenberg-pg2701-ch1",  # Moby-Dick — Melville
        url="https://www.gutenberg.org/cache/epub/2701/pg2701.txt",
        after_marker="CHAPTER 1.",
        skip_marker_occurrences=1,
    ),
    PoolSpec(
        source_id="gutenberg-pg84-ch1",  # Frankenstein — Shelley
        url="https://www.gutenberg.org/cache/epub/84/pg84.txt",
        after_marker="Letter 1",
        skip_marker_occurrences=1,
    ),
    PoolSpec(
        source_id="gutenberg-pg345-ch1",  # Dracula — Stoker
        url="https://www.gutenberg.org/cache/epub/345/pg345.txt",
        after_marker="CHAPTER I",
        skip_marker_occurrences=1,
    ),
    PoolSpec(
        source_id="gutenberg-pg1661-ch1",  # The Adventures of Sherlock Holmes — Doyle
        url="https://www.gutenberg.org/cache/epub/1661/pg1661.txt",
        after_marker="A SCANDAL IN BOHEMIA",
        skip_marker_occurrences=1,
    ),
    PoolSpec(
        source_id="gutenberg-pg98-ch1",  # A Tale of Two Cities — Dickens
        url="https://www.gutenberg.org/cache/epub/98/pg98.txt",
        after_marker="The Period",
        skip_marker_occurrences=1,
    ),
    PoolSpec(
        source_id="gutenberg-pg76-ch1",  # Adventures of Huckleberry Finn — Twain
        url="https://www.gutenberg.org/cache/epub/76/pg76.txt",
        after_marker="CHAPTER I.",
        skip_marker_occurrences=1,
    ),
    PoolSpec(
        source_id="gutenberg-pg174-ch1",  # The Picture of Dorian Gray — Wilde
        url="https://www.gutenberg.org/cache/epub/174/pg174.txt",
        after_marker="CHAPTER I.",
        skip_marker_occurrences=1,
    ),
    PoolSpec(
        source_id="gutenberg-pg35-ch1",  # The Time Machine — Wells
        url="https://www.gutenberg.org/cache/epub/35/pg35.txt",
        after_marker="The Time Traveller (for so it will be convenient",
    ),
    PoolSpec(
        source_id="gutenberg-pg36-ch1",  # The War of the Worlds — Wells
        url="https://www.gutenberg.org/cache/epub/36/pg36.txt",
        after_marker="No one would have believed",
    ),
    PoolSpec(
        source_id="gutenberg-pg408-ch1",  # The Souls of Black Folk — Du Bois
        url="https://www.gutenberg.org/cache/epub/408/pg408.txt",
        after_marker="Of Our Spiritual Strivings",
        skip_marker_occurrences=1,
    ),
    PoolSpec(
        source_id="gutenberg-pg55-ch1",  # The Wonderful Wizard of Oz — Baum
        url="https://www.gutenberg.org/cache/epub/55/pg55.txt",
        after_marker="The Cyclone",
        skip_marker_occurrences=1,
    ),
    PoolSpec(
        source_id="gutenberg-pg768-ch1",  # Wuthering Heights — E. Brontë
        url="https://www.gutenberg.org/cache/epub/768/pg768.txt",
        after_marker="CHAPTER I",
        skip_marker_occurrences=1,
    ),
    PoolSpec(
        source_id="gutenberg-pg1260-ch1",  # Jane Eyre — C. Brontë
        url="https://www.gutenberg.org/cache/epub/1260/pg1260.txt",
        after_marker="CHAPTER I",
        skip_marker_occurrences=1,
    ),
    PoolSpec(
        source_id="gutenberg-pg43-ch1",  # The Strange Case of Dr. Jekyll and Mr. Hyde — Stevenson
        url="https://www.gutenberg.org/cache/epub/43/pg43.txt",
        after_marker="STORY OF THE DOOR",
        skip_marker_occurrences=1,
    ),
    PoolSpec(
        source_id="gutenberg-pg120-ch1",  # Treasure Island — Stevenson
        url="https://www.gutenberg.org/cache/epub/120/pg120.txt",
        after_marker="THE OLD SEA-DOG",
        skip_marker_occurrences=1,
    ),
    PoolSpec(
        source_id="gutenberg-pg147-ch1",  # Common Sense — Paine
        url="https://www.gutenberg.org/cache/epub/147/pg147.txt",
        after_marker="OF THE ORIGIN AND DESIGN",
        skip_marker_occurrences=1,
    ),
    PoolSpec(
        source_id="gutenberg-pg25344-ch1",  # The Scarlet Letter — Hawthorne
        url="https://www.gutenberg.org/cache/epub/25344/pg25344.txt",
        after_marker="THE PRISON-DOOR",
        skip_marker_occurrences=1,
    ),
    PoolSpec(
        source_id="gutenberg-pg45-ch1",  # Anne of Green Gables — Montgomery
        url="https://www.gutenberg.org/cache/epub/45/pg45.txt",
        after_marker="MRS. RACHEL LYNDE IS SURPRISED",
        skip_marker_occurrences=1,
    ),
]


GUTENBERG_POOL = Pool(
    name="gutenberg",
    specs=GUTENBERG_SPECS,
    fetch_one=_fetch_gutenberg,
)


# -----------------------------------------------------------------------------
# Pool: federal-register (rules, proposed rules, notices)
# -----------------------------------------------------------------------------


# The Federal Register's full-text endpoint wraps the content in
# `<html><body><pre>...</pre></body></html>`. We strip that wrapper but
# preserve the inner pre-formatted text (which is already paragraph-shaped).
_FR_PRE_OPEN = re.compile(r"<pre>", re.IGNORECASE)
_FR_PRE_CLOSE = re.compile(r"</pre>", re.IGNORECASE)


def _strip_fr_pre_wrapper(raw: str) -> str:
    m_open = _FR_PRE_OPEN.search(raw)
    m_close = _FR_PRE_CLOSE.search(raw)
    if not (m_open and m_close):
        return raw
    inner = raw[m_open.end() : m_close.start()]
    # Inner text may still contain occasional HTML entities/anchors
    # introduced by the FR (e.g. ``<a href="...">www.gpo.gov</a>``).
    # ``html_to_text`` decodes entities and strips tags cleanly.
    return html_to_text(inner)


def _fetch_federal_register(spec: PoolSpec) -> str:
    """Fetch a Federal Register document by number via the open JSON API.

    ``spec.url`` is the API-metadata endpoint, e.g.
    ``https://www.federalregister.gov/api/v1/documents/<doc_number>``.
    We follow the response's ``raw_text_url`` to get the plain-text body
    (wrapped in ``<html><pre>...</pre></html>``), strip the wrapper, and
    excerpt.
    """
    meta = _http_get_json(spec.url)
    raw_url = meta.get("raw_text_url") or meta.get("body_html_url")
    if not raw_url:
        raise RuntimeError(f"no raw_text_url for {spec.source_id} ({spec.url})")
    raw = _http_get(raw_url)
    text = _strip_fr_pre_wrapper(raw)
    return _slice_excerpt(
        text,
        spec.after_marker,
        spec.max_chars,
        skip_marker_occurrences=spec.skip_marker_occurrences,
        before_marker=spec.before_marker,
    )


# Federal Register documents spanning 17 agencies and mixing Rule /
# Proposed Rule / Notice types. All verified to return >= 2000 words
# of body text after stripping the <pre> wrapper.
def _fr_url(doc_number: str) -> str:
    return f"https://www.federalregister.gov/api/v1/documents/{doc_number}"


FEDERAL_REGISTER_SPECS: list[PoolSpec] = [
    # EPA — Proposed Rules
    PoolSpec(source_id="fr-2025-22519", url=_fr_url("2025-22519")),  # pesticide tolerances
    PoolSpec(source_id="fr-2025-24134", url=_fr_url("2025-24134")),  # hazardous waste variance
    # FDA / HHS — Rule
    PoolSpec(source_id="fr-2025-21955", url=_fr_url("2025-21955")),  # medical devices QMS
    # FCC — Rules
    PoolSpec(source_id="fr-2025-23785", url=_fr_url("2025-23785")),  # AWS-3 spectrum auction
    PoolSpec(source_id="fr-2025-22633", url=_fr_url("2025-22633")),  # removal of obsolete regs
    # FTC — Rule
    PoolSpec(source_id="fr-2024-30293", url=_fr_url("2024-30293")),  # junk-fees trade reg
    # SEC — Proposed Rule
    PoolSpec(source_id="fr-2025-19152", url=_fr_url("2025-19152")),  # RMBS concept release
    # NRC — Rule
    PoolSpec(source_id="fr-2025-21784", url=_fr_url("2025-21784")),  # NRC sunset rule
    # OSHA / DOL — Rule
    PoolSpec(source_id="fr-2025-00539", url=_fr_url("2025-00539")),  # AMLA retaliation procedures
    # FAA / DOT — Rule
    PoolSpec(source_id="fr-2025-23858", url=_fr_url("2025-23858")),  # airworthiness directives
    # IRS / Treasury — Proposed Rule
    PoolSpec(source_id="fr-2025-23693", url=_fr_url("2025-23693")),  # transparency in coverage
    # CMS / HHS — Rule
    PoolSpec(source_id="fr-2025-21792", url=_fr_url("2025-21792")),  # LTC staffing repeal
    # NHTSA / DOT — Proposed Rules
    PoolSpec(source_id="fr-2025-22014", url=_fr_url("2025-22014")),  # SAFE Vehicles III
    PoolSpec(source_id="fr-2025-21506", url=_fr_url("2025-21506")),  # event data recorders
    # CPSC — Rule
    PoolSpec(source_id="fr-2025-22643", url=_fr_url("2025-22643")),  # water-beads safety standard
    # FWS / Interior — Rule
    PoolSpec(source_id="fr-2025-15703", url=_fr_url("2025-15703")),  # migratory-bird frameworks
    # Federal Reserve — Notice
    PoolSpec(source_id="fr-2025-23712", url=_fr_url("2025-23712")),  # payment-account RFI
    # DHS + DOJ — Rule
    PoolSpec(
        source_id="fr-2025-23970", url=_fr_url("2025-23970")
    ),  # security bars partial withdrawal
    # USCIS / DHS — Rule
    PoolSpec(source_id="fr-2024-16138", url=_fr_url("2024-16138")),  # IE program thresholds
    # USDA / FCIC — Rule
    PoolSpec(source_id="fr-2025-21482", url=_fr_url("2025-21482")),  # EARP risk protection
]


FEDERAL_REGISTER_POOL = Pool(
    name="federal-register",
    specs=FEDERAL_REGISTER_SPECS,
    fetch_one=_fetch_federal_register,
)


# -----------------------------------------------------------------------------
# Pool: usc (United States Code)
# -----------------------------------------------------------------------------


def _fetch_usc(spec: PoolSpec) -> str:
    """Fetch a US Code section as HTML and convert to plain text."""
    html = _http_get(spec.url)
    text = html_to_text(html)
    return _slice_excerpt(
        text,
        spec.after_marker,
        spec.max_chars,
        skip_marker_occurrences=spec.skip_marker_occurrences,
        before_marker=spec.before_marker,
    )


# US Code sections spanning 16 titles. All verified to return >= 2000
# words after html_to_text cleanup (range: 4.5k to 62k words).
def _usc_url(title: str, section: str) -> str:
    return (
        "https://uscode.house.gov/view.xhtml?"
        f"req=granuleid:USC-prelim-title{title}-section{section}"
        "&num=0&edition=prelim"
    )


USC_SPECS: list[PoolSpec] = [
    PoolSpec(source_id="usc-7-1508", url=_usc_url("7", "1508")),  # crop insurance
    PoolSpec(source_id="usc-11-101", url=_usc_url("11", "101")),  # bankruptcy defs
    PoolSpec(source_id="usc-12-1813", url=_usc_url("12", "1813")),  # FDIC defs
    PoolSpec(source_id="usc-15-78c", url=_usc_url("15", "78c")),  # Exchange Act defs
    PoolSpec(source_id="usc-17-512", url=_usc_url("17", "512")),  # DMCA safe harbor
    PoolSpec(source_id="usc-18-1956", url=_usc_url("18", "1956")),  # money laundering
    PoolSpec(source_id="usc-18-924", url=_usc_url("18", "924")),  # firearms penalties
    PoolSpec(source_id="usc-19-1677", url=_usc_url("19", "1677")),  # AD/CVD defs
    PoolSpec(source_id="usc-21-355", url=_usc_url("21", "355")),  # new drug approval
    PoolSpec(source_id="usc-21-802", url=_usc_url("21", "802")),  # CSA defs
    PoolSpec(source_id="usc-22-2778", url=_usc_url("22", "2778")),  # arms export control
    PoolSpec(source_id="usc-26-501", url=_usc_url("26", "501")),  # tax-exempt orgs
    PoolSpec(source_id="usc-26-401", url=_usc_url("26", "401")),  # qualified plans
    PoolSpec(source_id="usc-29-1002", url=_usc_url("29", "1002")),  # ERISA defs
    PoolSpec(source_id="usc-33-1321", url=_usc_url("33", "1321")),  # oil pollution
    PoolSpec(source_id="usc-38-1114", url=_usc_url("38", "1114")),  # veterans disability
    PoolSpec(source_id="usc-42-1395cc", url=_usc_url("42", "1395cc")),  # Medicare agreements
    PoolSpec(source_id="usc-42-7412", url=_usc_url("42", "7412")),  # Clean Air HAPs
    PoolSpec(source_id="usc-47-227", url=_usc_url("47", "227")),  # TCPA
    PoolSpec(source_id="usc-50-1881a", url=_usc_url("50", "1881a")),  # FISA §702
]


USC_POOL = Pool(name="usc", specs=USC_SPECS, fetch_one=_fetch_usc)


# -----------------------------------------------------------------------------
# Pool: wikipedia (English Wikipedia article extracts)
# -----------------------------------------------------------------------------


def _fetch_wikipedia(spec: PoolSpec) -> str:
    """Fetch an English-Wikipedia article's plain-text extract.

    ``spec.url`` is the full MediaWiki API URL, e.g.
    ``https://en.wikipedia.org/w/api.php?action=query&prop=extracts&exlimit=1&titles=Mercury_(planet)&explaintext=1&format=json``.
    The ``extracts`` extension returns plain text in the ``extract``
    field of the page entry.
    """
    data = _http_get_json(spec.url)
    pages = data.get("query", {}).get("pages", {})
    if not pages:
        raise RuntimeError(f"no pages in extract response for {spec.source_id}")
    # The pages dict is keyed by page-id (or "-1" for missing pages).
    page = next(iter(pages.values()))
    if page.get("missing") is not None:
        raise RuntimeError(f"wikipedia page missing for {spec.source_id} ({spec.url})")
    body = page.get("extract") or ""
    return _slice_excerpt(
        body,
        spec.after_marker,
        spec.max_chars,
        skip_marker_occurrences=spec.skip_marker_occurrences,
        before_marker=spec.before_marker,
    )


# Wikipedia article extracts. All entries verified to return >= 5000 words
# of plain text via the MediaWiki extracts API. URL pattern:
#   https://en.wikipedia.org/w/api.php?action=query&prop=extracts&exlimit=1
#     &titles=<title>&explaintext=1&format=json
# The literal parentheses in titles like "Mercury (planet)" pass through
# unescaped; the API accepts them either way.
_WIKI_TEMPLATE = (
    "https://en.wikipedia.org/w/api.php?action=query&prop=extracts"
    "&exlimit=1&titles={title}&explaintext=1&format=json"
)


def _wiki_url(title: str) -> str:
    return _WIKI_TEMPLATE.format(title=title)


WIKIPEDIA_SPECS: list[PoolSpec] = [
    # Science / Nature
    PoolSpec(source_id="wikipedia-mercury-planet", url=_wiki_url("Mercury_(planet)")),
    PoolSpec(source_id="wikipedia-black-hole", url=_wiki_url("Black_hole")),
    PoolSpec(source_id="wikipedia-dna", url=_wiki_url("DNA")),
    PoolSpec(source_id="wikipedia-photosynthesis", url=_wiki_url("Photosynthesis")),
    PoolSpec(source_id="wikipedia-plate-tectonics", url=_wiki_url("Plate_tectonics")),
    # History
    PoolSpec(source_id="wikipedia-roman-empire", url=_wiki_url("Roman_Empire")),
    PoolSpec(source_id="wikipedia-byzantine-empire", url=_wiki_url("Byzantine_Empire")),
    PoolSpec(source_id="wikipedia-han-dynasty", url=_wiki_url("Han_dynasty")),
    PoolSpec(source_id="wikipedia-silk-road", url=_wiki_url("Silk_Road")),
    PoolSpec(source_id="wikipedia-ancient-egypt", url=_wiki_url("Ancient_Egypt")),
    # Geography
    PoolSpec(source_id="wikipedia-amazon-rainforest", url=_wiki_url("Amazon_rainforest")),
    # Nile and Sahara had Arabic content that reportlab's LTR-only text
    # engine couldn't render bidirectionally — dropped in favour of two
    # other geography articles with the same word-count profile.
    PoolSpec(source_id="wikipedia-volcano", url=_wiki_url("Volcano")),
    PoolSpec(source_id="wikipedia-mariana-trench", url=_wiki_url("Mariana_Trench")),
    PoolSpec(source_id="wikipedia-great-barrier-reef", url=_wiki_url("Great_Barrier_Reef")),
    PoolSpec(source_id="wikipedia-mount-everest", url=_wiki_url("Mount_Everest")),
    # Technology / Engineering
    PoolSpec(
        source_id="wikipedia-internal-combustion-engine",
        url=_wiki_url("Internal_combustion_engine"),
    ),
    PoolSpec(source_id="wikipedia-steam-engine", url=_wiki_url("Steam_engine")),
    PoolSpec(source_id="wikipedia-hoover-dam", url=_wiki_url("Hoover_Dam")),
    PoolSpec(source_id="wikipedia-panama-canal", url=_wiki_url("Panama_Canal")),
    PoolSpec(
        source_id="wikipedia-international-space-station",
        url=_wiki_url("International_Space_Station"),
    ),
]


WIKIPEDIA_POOL = Pool(
    name="wikipedia",
    specs=WIKIPEDIA_SPECS,
    fetch_one=_fetch_wikipedia,
)


# -----------------------------------------------------------------------------
# Pool: agency-pubs (federal agency factsheets / short reports)
# -----------------------------------------------------------------------------


def _fetch_agency_pubs(spec: PoolSpec) -> str:
    # NIH NINDS, CDC, EPA and others bot-block library UAs; use Chrome.
    html = _http_get(spec.url, user_agent=CHROME_UA)
    text = html_to_text(html)
    return _slice_excerpt(
        text,
        spec.after_marker,
        spec.max_chars,
        skip_marker_occurrences=spec.skip_marker_occurrences,
        before_marker=spec.before_marker,
    )


# Federal agency publications: factsheets, technical guides, and
# consumer guides across 10 agencies. All verified to return >= 2000
# words after html_to_text cleanup. Some agencies (BLS, FSIS, MyPlate)
# returned 403/JS-only and were excluded.
AGENCY_PUBS_SPECS: list[PoolSpec] = [
    # CDC — Pink Book chapters + clinical / disease pages
    PoolSpec(
        source_id="cdc-pinkbook-mmr",
        url="https://www.cdc.gov/pinkbook/hcp/table-of-contents/chapter-13-measles.html",
    ),
    PoolSpec(
        source_id="cdc-pinkbook-flu",
        url="https://www.cdc.gov/pinkbook/hcp/table-of-contents/chapter-12-influenza.html",
    ),
    PoolSpec(
        source_id="cdc-dpdx-malaria",
        url="https://www.cdc.gov/dpdx/malaria/index.html",
    ),
    # NIH — NINDS disorder overviews + NCI basics
    PoolSpec(
        source_id="nih-parkinsons",
        url="https://www.ninds.nih.gov/health-information/disorders/parkinsons-disease",
    ),
    PoolSpec(
        source_id="nih-epilepsy",
        url="https://www.ninds.nih.gov/health-information/disorders/epilepsy-and-seizures",
    ),
    PoolSpec(
        source_id="nih-cancer-what",
        url="https://www.cancer.gov/about-cancer/understanding/what-is-cancer",
    ),
    # NIST — metrology explainer
    PoolSpec(
        source_id="nist-si-units-length",
        url="https://www.nist.gov/pml/owm/si-units-length",
    ),
    # NOAA — weather / ocean / climate education
    PoolSpec(
        source_id="noaa-hurricanes",
        url="https://www.noaa.gov/education/resource-collections/weather-atmosphere/hurricanes",
    ),
    PoolSpec(
        source_id="noaa-tsunamis",
        url="https://www.noaa.gov/education/resource-collections/ocean-coasts/tsunamis",
    ),
    PoolSpec(
        source_id="noaa-elnino",
        url=(
            "https://www.climate.gov/news-features/understanding-climate/"
            "el-nino-and-la-nina-frequently-asked-questions"
        ),
    ),
    # USGS — Water Science School + hazards
    PoolSpec(
        source_id="usgs-water-use",
        url="https://www.usgs.gov/mission-areas/water-resources/science/water-use-united-states",
    ),
    PoolSpec(
        source_id="usgs-floods",
        url=(
            "https://www.usgs.gov/special-topics/water-science-school/science/"
            "floods-and-recurrence-intervals"
        ),
    ),
    PoolSpec(
        source_id="usgs-glaciers",
        url=(
            "https://www.usgs.gov/special-topics/water-science-school/science/glaciers-and-icecaps"
        ),
    ),
    # EPA — environmental health
    PoolSpec(source_id="epa-lead", url="https://www.epa.gov/lead/learn-about-lead"),
    PoolSpec(source_id="epa-radon", url="https://www.epa.gov/radon/health-risk-radon"),
    # FDA — consumer health
    PoolSpec(
        source_id="fda-radiation",
        url="https://www.fda.gov/radiation-emitting-products/medical-imaging/medical-x-ray-imaging",
    ),
    PoolSpec(
        source_id="fda-allergens",
        url="https://www.fda.gov/food/food-labeling-nutrition/food-allergies",
    ),
    # Treasury
    PoolSpec(
        source_id="treasury-debt-limit",
        url=(
            "https://home.treasury.gov/policy-issues/financial-markets-financial-"
            "institutions-and-fiscal-service/debt-limit"
        ),
    ),
    # Federal Reserve
    PoolSpec(
        source_id="fed-discount-window",
        url="https://www.federalreserve.gov/regreform/discount-window.htm",
    ),
    # USDA — Economic Research Service
    PoolSpec(
        source_id="usda-ers-foodsec",
        url=(
            "https://www.ers.usda.gov/topics/food-nutrition-assistance/"
            "food-security-in-the-u-s/measurement"
        ),
    ),
]


AGENCY_PUBS_POOL = Pool(
    name="agency-pubs",
    specs=AGENCY_PUBS_SPECS,
    fetch_one=_fetch_agency_pubs,
)


# -----------------------------------------------------------------------------
# Pool registry + CLI
# -----------------------------------------------------------------------------


ALL_POOLS: list[Pool] = [
    GUTENBERG_POOL,
    FEDERAL_REGISTER_POOL,
    USC_POOL,
    WIKIPEDIA_POOL,
    AGENCY_PUBS_POOL,
]

POOLS_BY_NAME: dict[str, Pool] = {p.name: p for p in ALL_POOLS}


def fetch_pool(name: str) -> list[ProvenanceRow]:
    pool = POOLS_BY_NAME.get(name)
    if pool is None:
        raise SystemExit(f"unknown pool {name!r}; known: {sorted(POOLS_BY_NAME)}")
    if not pool.specs:
        return []
    return _fetch_pool(pool)


def fetch_all() -> list[ProvenanceRow]:
    rows = []
    for pool in ALL_POOLS:
        if pool.specs:
            rows.extend(_fetch_pool(pool))
    return rows


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--pool",
        choices=[*POOLS_BY_NAME, "all"],
        default="all",
    )
    args = p.parse_args()

    rows = fetch_all() if args.pool == "all" else fetch_pool(args.pool)

    print(f"wrote {len(rows)} source(s) to {SOURCES_DIR}")
    for r in rows:
        print(f"  {r.source_id:35s} {r.pool:15s} {r.bytes_written:6d} bytes  {r.sha256[:12]}…")


if __name__ == "__main__":
    main()
