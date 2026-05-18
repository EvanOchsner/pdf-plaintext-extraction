"""Lazy fetch + register of a Unicode-capable TTF for homoglyph rendering.

reportlab's base fonts (Helvetica, Times, Courier) are Latin-1 only and
cannot render Cyrillic, Greek, or full-width Latin glyphs — exactly the
codepoint ranges the homoglyph poisoning technique substitutes into. We
need a TrueType font that has those glyphs.

DejaVu Sans is the standard choice for this: public-domain-friendly
Bitstream Vera license, ~750 KB, covers Latin Extended + Cyrillic +
Greek + many more scripts. We download it once on demand from the
upstream sourceforge mirror into ``.tmp/fonts/`` (gitignored), then
register it with reportlab.

If the download fails (e.g. offline), the calling technique raises
``RuntimeError`` and the harness records a graceful error row.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
FONT_CACHE = ROOT / ".tmp" / "fonts"

# DejaVuSans.ttf 2.37 (latest stable release). SHA-256 pinned below.
DEJAVU_URL = "https://downloads.sourceforge.net/project/dejavu/dejavu/2.37/dejavu-fonts-ttf-2.37.zip"
DEJAVU_TTF_NAME = "DejaVuSans.ttf"

# Sourceforge release zip SHA-256. Recorded so the fetch can verify the
# bytes after download.
DEJAVU_ZIP_SHA256 = "7576310b219e04159d35ff61dd4a4ec4cdba4f35c00e002a136f00e96a908b0a"

UA = "serff-extraction/0.0.1 (academic research)"


def _fetch_zip(target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with httpx.Client(
        headers={"User-Agent": UA}, timeout=60.0, follow_redirects=True
    ) as c:
        r = c.get(DEJAVU_URL)
        r.raise_for_status()
        target.write_bytes(r.content)


def ensure_dejavu_sans() -> Path:
    """Return a local filesystem path to DejaVuSans.ttf, fetching once if needed."""
    ttf_path = FONT_CACHE / DEJAVU_TTF_NAME
    if ttf_path.exists():
        return ttf_path

    zip_path = FONT_CACHE / "dejavu.zip"
    if not zip_path.exists():
        _fetch_zip(zip_path)

    sha = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    if sha != DEJAVU_ZIP_SHA256:
        zip_path.unlink(missing_ok=True)
        raise RuntimeError(
            f"DejaVu zip sha mismatch: expected {DEJAVU_ZIP_SHA256}, got {sha}. "
            "Refusing to use unverified font."
        )

    import zipfile

    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.namelist():
            if member.endswith("/" + DEJAVU_TTF_NAME):
                with zf.open(member) as src, ttf_path.open("wb") as dst:
                    dst.write(src.read())
                break
        else:
            raise RuntimeError(f"{DEJAVU_TTF_NAME} not found in zip")

    return ttf_path


def register_dejavu_with_reportlab(font_name: str = "DejaVuSans") -> str:
    """Register DejaVu Sans with reportlab and return the registered name."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    if font_name in pdfmetrics.getRegisteredFontNames():
        return font_name
    ttf = ensure_dejavu_sans()
    pdfmetrics.registerFont(TTFont(font_name, str(ttf)))
    return font_name
