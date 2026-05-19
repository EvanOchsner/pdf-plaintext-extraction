"""Tiny stdlib-only HTML-to-text helper for the source fetchers.

The fetchers consume HTML from a handful of well-structured public-domain
sources (uscode.house.gov, Cornell LII, CDC/NIH/BLS/USGS factsheets). A
full-featured library like BeautifulSoup or trafilatura would be overkill
and would add a new runtime dependency. Instead, this module ships a
minimal ``html.parser.HTMLParser``-based extractor that:

- Skips ``<script>``, ``<style>``, and ``<noscript>`` content entirely.
- Treats common block-level tags (``p``, ``div``, ``li``, ``br``,
  headings, table rows) as paragraph breaks.
- Decodes HTML entities via ``html.unescape``.
- Collapses runs of whitespace within a paragraph but preserves blank
  lines between paragraphs (so ``_slice_excerpt`` can walk back to the
  nearest paragraph boundary).

It is *not* a layout-preserving converter — but for the source fetchers
the goal is just to get clean plain text out of the body, not to
reconstruct the original styling.
"""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser

# Tags whose content we discard entirely.
_SKIP_TAGS = frozenset({"script", "style", "noscript", "head", "title"})

# Block-level tags whose closing implies a paragraph break.
_BLOCK_TAGS = frozenset(
    {
        "p",
        "div",
        "section",
        "article",
        "header",
        "footer",
        "main",
        "nav",
        "aside",
        "li",
        "ol",
        "ul",
        "blockquote",
        "pre",
        "tr",
        "table",
        "thead",
        "tbody",
        "tfoot",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
    }
)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._out: list[str] = []
        self._skip_depth = 0

    # --- tag handling --------------------------------------------------

    def handle_starttag(self, tag: str, _attrs) -> None:
        tag = tag.lower()
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
            return
        if tag == "br":
            self._out.append("\n")
        elif tag in _BLOCK_TAGS:
            self._out.append("\n\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in _SKIP_TAGS:
            if self._skip_depth > 0:
                self._skip_depth -= 1
            return
        if tag in _BLOCK_TAGS:
            self._out.append("\n\n")

    def handle_startendtag(self, tag: str, _attrs) -> None:
        tag = tag.lower()
        if tag == "br":
            self._out.append("\n")
        elif tag in _BLOCK_TAGS:
            self._out.append("\n\n")

    # --- text handling -------------------------------------------------

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._out.append(data)

    # --- output --------------------------------------------------------

    def get_text(self) -> str:
        return "".join(self._out)


# Collapse 3+ consecutive blank lines to exactly one blank line.
_MULTI_BLANK = re.compile(r"\n{3,}")
# Collapse runs of inline whitespace (spaces, tabs) to a single space,
# but preserve newlines (so paragraph structure survives).
_INLINE_WS = re.compile(r"[ \t]+")


def html_to_text(raw_html: str) -> str:
    """Convert an HTML document to clean plain text.

    The output is paragraph-shaped: paragraphs are separated by exactly
    one blank line, runs of inline whitespace are collapsed to a single
    space, and HTML entities are decoded.
    """
    parser = _TextExtractor()
    parser.feed(raw_html)
    parser.close()
    text = parser.get_text()

    # Decode any entities the parser left behind (convert_charrefs handles
    # most, but legacy &amp; in CDATA-like contexts may need this).
    text = html.unescape(text)

    # Normalize whitespace.
    lines = []
    for line in text.split("\n"):
        line = _INLINE_WS.sub(" ", line).strip()
        lines.append(line)
    text = "\n".join(lines)
    text = _MULTI_BLANK.sub("\n\n", text)
    return text.strip()
