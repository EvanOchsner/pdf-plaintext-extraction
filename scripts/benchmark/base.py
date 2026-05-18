"""Common types for the W5 benchmark harness."""

from __future__ import annotations

import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass
class ExtractionResult:
    extractor_name: str
    pdf_path: str
    text: str
    per_page_text: list[str] = field(default_factory=list)
    wall_seconds: float = 0.0
    error: str | None = None
    extra: dict[str, object] = field(default_factory=dict)


class Extractor(Protocol):
    """Interface every extractor wrapper implements.

    Wrappers should NOT raise on extraction failure — instead they should
    return an ``ExtractionResult`` with ``error`` set. The harness
    treats raised exceptions as a wrapper bug, not an extraction outcome.
    """

    name: str

    def extract(self, pdf_path: Path) -> ExtractionResult: ...


def timed(name: str, pdf_path: Path, fn) -> ExtractionResult:
    """Run ``fn() -> (text, per_page_text)`` and wrap the result with
    timing + error capture."""
    t0 = time.perf_counter()
    try:
        text, per_page = fn()
        return ExtractionResult(
            extractor_name=name,
            pdf_path=str(pdf_path),
            text=text or "",
            per_page_text=list(per_page or []),
            wall_seconds=time.perf_counter() - t0,
        )
    except Exception as e:  # noqa: BLE001 - intentional broad catch
        return ExtractionResult(
            extractor_name=name,
            pdf_path=str(pdf_path),
            text="",
            wall_seconds=time.perf_counter() - t0,
            error=f"{type(e).__name__}: {e}",
        )


def run_all(
    extractors: Iterable[Extractor], pdf_paths: Iterable[Path]
) -> list[ExtractionResult]:
    results = []
    for ext in extractors:
        for pdf in pdf_paths:
            results.append(ext.extract(pdf))
    return results
