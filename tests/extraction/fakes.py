"""FakeExtractionBackend (C9) — the FakeCaller pattern applied to the
extraction seam: the offline suite proves every wire without docling.

Scriptable per document name: a canned view dict, an ExtractionFailed, or
a partial_success view. Keys may be either "<name>" or "<name>:vlm" — the
vlm key serves the two-path diff tests (C10)."""

from pathlib import Path

from engine.extraction.backend import ExtractionFailed
from engine.extraction.model import ExtractionView


def simple_view(text: str = "body", *, pages: int = 1, grids: list | None = None,
                status: str = "success", page_texts: list | None = None,
                figures: list | None = None,
                multicolumn_pages: list | None = None) -> dict:
    """A minimal valid view dict tests can extend."""
    return {
        "text": text,
        "pages": pages,
        "grids": grids or [],
        "figures": figures or [],
        "page_texts": page_texts,
        "multicolumn_pages": multicolumn_pages or [],
        "status": status,
        "docling_version": "0.0-fake",
    }


class FakeExtractionBackend:
    identity = "docling"

    def __init__(self, views: dict | None = None):
        self.views = views or {}
        self.calls: list[tuple[str, str]] = []

    def convert(self, path: Path, mode: str = "deterministic") -> ExtractionView:
        name = Path(path).name
        self.calls.append((name, mode))
        key = f"{name}:{mode}" if mode != "deterministic" else name
        scripted = self.views.get(key, self.views.get(name))
        if scripted is None:
            raise ExtractionFailed(f"{path}: no scripted view for {key!r}")
        if isinstance(scripted, Exception):
            raise scripted
        return ExtractionView.from_dict(scripted)
