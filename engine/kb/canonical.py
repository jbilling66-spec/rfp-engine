"""L1 canonical document model (C3, WP13 R1/R2).

Every source format resolves to this ONE persisted shape; nothing enters
the KB except through it. The model is stack-agnostic by design (B57
affirmed at B59): producers — the python-docx KB reader and the P12
ExtractionView adapter — emit the same neutral element list, so swapping
stacks is a producer change, never a model change.

Two invariants the persistence layer owns:
  - ANONYMIZED text only (R7): ingest runs apply_placeholders + the scan
    gate over every element BEFORE write_model; raw parsed output never
    reaches kb/canonical/. This module trusts its caller on that and the
    ingest tests enforce the ordering.
  - Clock-free, key-sorted bytes: the file is part of the byte-golden
    seed store and must be identical across kill/resume and across
    machines. No timestamps, no environment, sorted keys.

Chunks carry their element span (the L2->L1 derivation link, R2) and a
kb_id backref once the card is minted — the backrefs are what make
heading-path descent a single-file read instead of a catalog scan (R9).
"""

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from engine.contracts import validate
from engine.kb.store import _atomic_write_text

ELEMENT_KINDS = ("heading", "paragraph", "table_row", "figure", "qa")

FIGURE_CLASSES = frozenset(
    {"chart", "diagram", "logo", "signature", "screenshot", "photo", "other"}
)

_ELEMENT_KEYS = {"kind", "text", "level", "page", "figure_class"}
_CHUNK_KEYS = {"doc_path", "elements", "chars", "pages", "kb_id"}
_MODEL_KEYS = {"doc_id", "source_hash", "extractor", "extraction_fingerprint",
               "extraction_status", "media", "elements", "chunks"}


@dataclass
class Element:
    kind: str
    text: str
    level: int | None = None
    page: int | None = None
    figure_class: str | None = None

    def to_dict(self) -> dict:
        out: dict = {"kind": self.kind, "text": self.text}
        if self.level is not None:
            out["level"] = self.level
        if self.page is not None:
            out["page"] = self.page
        if self.figure_class is not None:
            out["figure_class"] = self.figure_class
        return out

    @classmethod
    def from_dict(cls, data: dict) -> "Element":
        unknown = set(data) - _ELEMENT_KEYS
        if unknown:
            raise ValueError(f"unknown element key(s) {sorted(unknown)}")
        return cls(**data)


@dataclass
class Chunk:
    doc_path: list[str]
    elements: tuple[int, int]
    chars: int
    pages: list[int] = field(default_factory=list)
    kb_id: str | None = None

    def to_dict(self) -> dict:
        out: dict = {"doc_path": list(self.doc_path),
                     "elements": list(self.elements),
                     "chars": self.chars}
        if self.pages:
            out["pages"] = list(self.pages)
        if self.kb_id is not None:
            out["kb_id"] = self.kb_id
        return out

    @classmethod
    def from_dict(cls, data: dict) -> "Chunk":
        unknown = set(data) - _CHUNK_KEYS
        if unknown:
            raise ValueError(f"unknown chunk key(s) {sorted(unknown)}")
        data = dict(data)
        data["elements"] = tuple(data["elements"])
        return cls(**data)


@dataclass
class CanonicalDoc:
    doc_id: str
    source_hash: str
    extractor: str
    extraction_fingerprint: str
    extraction_status: str
    elements: list[Element]
    chunks: list[Chunk]
    media: dict = field(default_factory=lambda: {"images": 0})

    def to_dict(self) -> dict:
        return {
            "doc_id": self.doc_id,
            "source_hash": self.source_hash,
            "extractor": self.extractor,
            "extraction_fingerprint": self.extraction_fingerprint,
            "extraction_status": self.extraction_status,
            "media": dict(self.media),
            "elements": [e.to_dict() for e in self.elements],
            "chunks": [c.to_dict() for c in self.chunks],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CanonicalDoc":
        unknown = set(data) - _MODEL_KEYS
        if unknown:
            raise ValueError(f"unknown canonical-doc key(s) {sorted(unknown)}")
        return cls(
            doc_id=data["doc_id"],
            source_hash=data["source_hash"],
            extractor=data["extractor"],
            extraction_fingerprint=data["extraction_fingerprint"],
            extraction_status=data["extraction_status"],
            media=dict(data.get("media", {"images": 0})),
            elements=[Element.from_dict(e) for e in data["elements"]],
            chunks=[Chunk.from_dict(c) for c in data["chunks"]],
        )


def source_hash_for(source_bytes: bytes) -> str:
    return hashlib.sha256(source_bytes).hexdigest()


def doc_id_for(source_bytes: bytes) -> str:
    """Content-addressed from the L0 bytes: the same source always
    resolves to the same model file, which is what makes re-ingestion a
    reconciliation instead of a duplication."""
    return "cd_" + source_hash_for(source_bytes)[:12]


def canonical_dir(kb_root: Path) -> Path:
    return Path(kb_root) / "canonical"


def model_path(kb_root: Path, doc_id: str) -> Path:
    return canonical_dir(kb_root) / f"{doc_id}.json"


def write_model(kb_root: Path, model: CanonicalDoc) -> Path:
    payload = model.to_dict()
    validate("canonical_doc", payload)
    path = model_path(kb_root, model.doc_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(
        path, json.dumps(payload, indent=1, sort_keys=True) + "\n")
    return path


def read_model(kb_root: Path, doc_id: str) -> CanonicalDoc:
    payload = json.loads(
        model_path(kb_root, doc_id).read_text(encoding="utf-8"))
    validate("canonical_doc", payload)
    return CanonicalDoc.from_dict(payload)


# ---------------------------------------------------------------- producers
#
# Both stacks emit into the SAME element list (B57 affirmed at B59): the
# python-docx KB reader walks its document directly (engine/kb/read.py),
# and the docling path parses the view's markdown export below. The swap
# point, should A1 evidence reopen B57, is one call-site change in the
# ingest pipeline: read_source(path) -> resolve_backend().convert(path)
# + elements_from_extraction_view(view). Same model either way.

_HEADING_LINE = re.compile(r"^(#{1,6}) (.+)$")
_HTML_COMMENT_LINE = re.compile(r"^<!--.*-->$")
# The repo-wide caller-script marker ('# DOC:resp_01' leads every fixture
# and eval doc; scripted callers key off it). Harness scaffolding, same
# status as the meta comment: it must never become an L1 heading or the
# root of every doc_path.
_DOC_MARKER_LINE = re.compile(r"^# DOC:\S+$")


def _is_separator_row(cells: list[str]) -> bool:
    return bool(cells) and all(
        re.fullmatch(r":?-{2,}:?", c) for c in cells)


def elements_from_markdown(text: str) -> list[Element]:
    """Markdown/flat-text lines -> elements. Handles the conventions both
    stacks already write: '#'-prefixed headings, pipe table rows (docling's
    export renders tables this way; separator rows are structure, not
    content). Consecutive plain lines group into one paragraph element.
    HTML comment lines are harness metadata (the eval doc_meta line) —
    they stay OUT of the model so their identifiers never reach L1."""
    elements: list[Element] = []
    paragraph: list[str] = []

    def flush() -> None:
        if paragraph:
            elements.append(
                Element(kind="paragraph", text="\n".join(paragraph)))
            paragraph.clear()

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            flush()
            continue
        if _HTML_COMMENT_LINE.match(line) or _DOC_MARKER_LINE.match(line):
            flush()
            continue
        heading = _HEADING_LINE.match(line)
        if heading:
            flush()
            elements.append(Element(kind="heading",
                                    text=heading.group(2).strip(),
                                    level=len(heading.group(1))))
            continue
        if line.startswith("|") and line.endswith("|") and len(line) > 1:
            cells = [c.strip() for c in line[1:-1].split("|")]
            if _is_separator_row(cells):
                continue
            flush()
            elements.append(Element(
                kind="table_row",
                text=" | ".join(c for c in cells if c)))
            continue
        paragraph.append(line)
    flush()
    return elements


def elements_from_extraction_view(view) -> list[Element]:
    """engine.extraction.model.ExtractionView -> elements (venv-safe: the
    view is pure dataclasses; docling itself never imports here). PDFs
    carry per-page provenance through page_texts; figures append with
    their top classification, unknown labels folded to 'other'."""
    elements: list[Element] = []
    if view.page_texts:
        for page_no, page_text in enumerate(view.page_texts, start=1):
            for element in elements_from_markdown(page_text):
                element.page = page_no
                elements.append(element)
    else:
        elements = elements_from_markdown(view.text)
    for figure in view.figures:
        label = None
        if figure.classes:
            top = max(figure.classes,
                      key=lambda c: c.get("confidence", 0.0))
            label = top.get("label")
            if label is not None and label not in FIGURE_CLASSES:
                label = "other"
        elements.append(
            Element(kind="figure", text="", figure_class=label))
    return elements


def view_extraction_status(view) -> str:
    """docling's partial_success is the degraded-still-ingests case (X6)."""
    return "degraded" if view.status == "partial_success" else "clean"
