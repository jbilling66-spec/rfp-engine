"""Typed extraction view (C8) — the shape the §A2 gate proved, now a contract.

The gate's convert worker (gate.py) returns a plain dict; C7 froze its shape
as evidence. Production code (the C9 backend and the intake adapter) must not
consume an untyped dict across a process boundary, so this module gives that
exact shape a name. `from_dict` is strict: an unknown key is a refusal, not a
silent drop — a worker emitting a field nobody models is a contract drift.

Timing fields (`seconds`, `seconds_cold`, `timing_basis`) are deliberately
NOT part of the view: they are gate-report evidence, and production artifacts
must be byte-identical across kill/resume (brief.py) — no wall clock crosses
this boundary.
"""

from dataclasses import dataclass, field

# The container vocabulary, verbatim from the spec's §A5 sentence
# (spec/handoff/EXTRACTION_AND_SCALE_SPEC.md): these labels are NEVER
# written into type_tags — a table is not a kind of knowledge. The
# disjointness is test-pinned against kb.ingest.TYPE_TAGS (C13).
DOCLING_ELEMENT_LABELS = frozenset(
    {"section_header", "table", "list_item", "figure", "formula"}
)


@dataclass
class TableView:
    grid: list  # list[list[str]], rectangular
    merges: list = field(default_factory=list)  # [[[r0,c0],[r1,c1]], ...]


@dataclass
class FigureView:
    classes: list = field(default_factory=list)  # [{label, confidence}]


_VIEW_KEYS = {
    "grids",
    "headings",
    "figures",
    "native_comment_texts",
    "sidecar",
    "text",
    "pages",
    "page_texts",
    "multicolumn_pages",
    "status",
    "docling_version",
}


@dataclass
class ExtractionView:
    text: str  # markdown export (or page-marked text, see page_texts)
    pages: int
    grids: list = field(default_factory=list)  # list[TableView]
    headings: list = field(default_factory=list)  # [[level, text], ...]
    figures: list = field(default_factory=list)  # list[FigureView]
    native_comment_texts: list = field(default_factory=list)
    sidecar: dict = field(default_factory=lambda: {"fills": {}, "comment_texts": []})
    page_texts: list | None = None  # per-page text for [page N] markers (PDF)
    multicolumn_pages: list = field(default_factory=list)  # filled by C13
    status: str = "success"  # docling status: success | partial_success
    docling_version: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "ExtractionView":
        unknown = set(data) - _VIEW_KEYS
        if unknown:
            raise ValueError(
                f"extraction view carries unmodeled keys: {sorted(unknown)}"
            )
        missing = {"text", "pages"} - set(data)
        if missing:
            raise ValueError(f"extraction view missing keys: {sorted(missing)}")
        out = dict(data)
        out["grids"] = [
            TableView(grid=g["grid"], merges=g.get("merges", []))
            for g in data.get("grids", [])
        ]
        out["figures"] = [
            FigureView(classes=f.get("classes", [])) for f in data.get("figures", [])
        ]
        return cls(**out)

    def to_dict(self) -> dict:
        return {
            "grids": [{"grid": t.grid, "merges": t.merges} for t in self.grids],
            "headings": self.headings,
            "figures": [{"classes": f.classes} for f in self.figures],
            "native_comment_texts": self.native_comment_texts,
            "sidecar": self.sidecar,
            "text": self.text,
            "pages": self.pages,
            "page_texts": self.page_texts,
            "multicolumn_pages": self.multicolumn_pages,
            "status": self.status,
            "docling_version": self.docling_version,
        }
