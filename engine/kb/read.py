"""KB source reader — python-docx PRIMARY on the KB-distillation path
(B57; reopener fired at P13 and AFFIRMED, B59: architectural evidence
only, next trigger is A1 real-corpus evidence).

P13/C4 upgraded the C12 flat reader to emit STRUCTURE: the same walk
that builds the flat text now also builds the canonical element list
(engine/kb/canonical.py) — headings with levels, paragraphs, table rows
— so the L1 model is built from python-docx without a docling
dependency. The flat `text` conventions are byte-unchanged (headings as
'#' lines, tables as pipe rows) and remain REIMPLEMENTED, not imported
from intake: the two paths are separate stacks by verdict, each with its
own fingerprint (test_seam_loudness pins both).

Media facts exist because the anonymization gate is text-only: a logo or
signature IMAGE carries client identity no string scan can see — the
reader counts embedded images so ingest can flag the document (C11).

P33b (B153): a completed response workbook is read HERE, in-engine —
`.xlsx` pairs through engine.structure.response and the elements are
built directly (no markdown round-trip), stamped `openpyxl` with the
pairing's own version in the fingerprint; and the reader has one typed
refusal, UnreadableSource, for everything it cannot honestly read
(P3-24). The converter (`kb pair`) stays as the zero-spend preview."""

import importlib.metadata
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from engine.extraction.fingerprint import stack_fingerprint
from engine.kb.canonical import Element, elements_from_markdown
from engine.kb.response_workbook import (
    DEGRADING_SKIPS,
    PROVENANCE_PREFIX,
    RESPONSE_PARSER_VERSION,
    ResponseWorkbookError,
    elements_from_response,
    pair_response_workbook,
    render_markdown,
)
from engine.structure.zipguard import check_office_zip

# P3-24 (P33b, B153 §2): suffixes the KB has no reader for — refused by name
# before a byte is read, never decoded as text. A PDF is P2-64's door.
_BINARY_SUFFIXES = frozenset({
    ".pdf", ".doc", ".dot", ".rtf", ".odt", ".ppt", ".pptx", ".odp", ".key",
    ".xls", ".xlsm", ".xlsb", ".ods", ".numbers", ".pages",
    ".zip", ".7z", ".gz", ".tar", ".rar", ".msg",
    ".png", ".jpg", ".jpeg", ".gif", ".tif", ".tiff", ".bmp", ".heic", ".webp",
})
_READERS = ".docx, .xlsx, markdown/text"


class UnreadableSource(Exception):
    """The reader's one typed refusal (P3-24, P33b): a path and a why — the
    intake door's `UnreadableRfp` precedent. `warnings` carries the pairing's
    addresses when a workbook read found nothing to pair."""

    def __init__(self, path, why: str, warnings: tuple[str, ...] = ()):
        self.path = str(path)
        self.why = why
        self.warnings = list(warnings)
        super().__init__(f"{path}: {why}")


@dataclass
class SourceText:
    text: str
    extractor: str  # "python-docx" | "openpyxl" | "text"
    fingerprint: str
    media: dict = field(default_factory=lambda: {"images": 0})
    elements: list = field(default_factory=list)  # list[canonical.Element]
    # P33b: what the reader knows that the ingest records — the card
    # kind (a workbook is a past response), whether content was LOST on
    # the way (hidden or uncached cells: degraded, still ingests — ingest
    # 1b), and the pairing's warnings, addresses only.
    doc_kind: str = "section_exemplar"
    degraded: bool = False
    warnings: list = field(default_factory=list)


def _docx_fingerprint() -> str:
    return stack_fingerprint(
        "python-docx",
        {"extractor_version": importlib.metadata.version("python-docx")},
    )


def _read_docx(path: Path) -> SourceText:
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    check_office_zip(path)  # P0-8: the container before the parser
    from engine.structure.docx_parts import header_footer_text, text_box_text

    document = docx.Document(str(path))
    lines: list[str] = []
    elements: list[Element] = []
    parts = header_footer_text(document)  # P2-27: headers first, footers last
    for kind, text in parts:
        if kind == "header":
            lines.append(f"[header] {text}")
            elements.append(Element(kind="paragraph", text=text))
    for item in document.iter_inner_content():
        if isinstance(item, Paragraph):
            style = item.style.name if item.style is not None else ""
            match = re.fullmatch(r"Heading (\d)", style or "")
            if match and item.text.strip():
                lines.append("#" * int(match.group(1)) + " " + item.text)
                elements.append(Element(kind="heading",
                                        text=item.text.strip(),
                                        level=int(match.group(1))))
            elif item.text.strip():
                lines.append(item.text)
                elements.append(Element(kind="paragraph",
                                        text=item.text.strip()))
            for boxed in text_box_text(item._p):  # P2-27
                lines.append(f"[text box] {boxed}")
                elements.append(Element(kind="paragraph", text=boxed))
        elif isinstance(item, Table):
            for row in item.rows:
                texts = [c.text.replace("\n", " ") for c in row.cells
                         if c.text.strip()]
                if texts:
                    lines.append("| " + " | ".join(texts) + " |")
                    elements.append(Element(kind="table_row",
                                            text=" | ".join(texts)))
    for kind, text in parts:  # P2-27: footers last
        if kind == "footer":
            lines.append(f"[footer] {text}")
            elements.append(Element(kind="paragraph", text=text))
    try:
        images = len(document.part.package.image_parts)
    except AttributeError:
        images = len(document.inline_shapes)
    return SourceText(
        text="\n".join(lines),
        extractor="python-docx",
        fingerprint=_docx_fingerprint(),
        media={"images": images},
        elements=elements,
    )


# ---- the response workbook (P33b) -----------------------------------------

def _xlsx_fingerprint() -> str:
    return stack_fingerprint("openpyxl", {
        "extractor_version": importlib.metadata.version("openpyxl"),
        "response_parser_version": RESPONSE_PARSER_VERSION,
    })


def _xlsx_media(path: Path) -> int:
    """Embedded pictures live under xl/media/ — counted from the container
    (already guarded by the pairing's read), never rendered: a logo in a
    response workbook is identity no text scan sees (C11)."""
    with zipfile.ZipFile(path) as zf:
        return sum(1 for name in zf.namelist() if name.startswith("xl/media/"))


def _read_xlsx(path: Path) -> SourceText:
    """A completed response workbook, read in-engine (B153 §2): the pairing
    says what was said, the elements are built directly — so an answer line
    that LOOKS like markdown structure is plain text here, never refused —
    and the flat text is the lossless rendering. Nothing to pair is a
    refusal: an ingest retains L0 before it mints, and an empty read should
    leave nothing behind (§3d)."""
    try:
        book = pair_response_workbook(path)
    except ResponseWorkbookError as exc:
        raise UnreadableSource(
            path, str(exc).removeprefix(f"{path.name}: ")) from exc
    if not book.pairs():
        raise UnreadableSource(
            path, "no question/answer pairs found — nothing to ingest "
                  "(the pairing's warnings follow, by address)",
            tuple(book.warnings))
    return SourceText(
        text=render_markdown(book, refuse_structural=False).text,
        extractor="openpyxl",
        fingerprint=_xlsx_fingerprint(),
        media={"images": _xlsx_media(path)},
        elements=elements_from_response(book),
        doc_kind="past_response",
        degraded=any(kind in DEGRADING_SKIPS for kind in book.skipped),
        warnings=list(book.warnings),
    )


def read_source(path: Path) -> SourceText:
    """One source document -> text + stack identity + media facts. Raises
    UnreadableSource (typed, P3-24) for a binary the KB has no reader for, a
    junk workbook container, a workbook with nothing to pair, or a text file
    that is not UTF-8; `.md` and `.txt` read exactly as before."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return _read_docx(path)
    if suffix == ".xlsx":
        return _read_xlsx(path)
    if suffix in _BINARY_SUFFIXES:
        raise UnreadableSource(
            path, f"no KB reader for {suffix!r} (readers: {_READERS})")
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise UnreadableSource(
            path, "not UTF-8 text and not a document type the KB reads "
                  f"(readers: {_READERS})") from exc
    return SourceText(
        text=text,
        extractor="text",
        fingerprint=stack_fingerprint("text", {"extractor_version": "stdlib"}),
        elements=elements_from_markdown(text),
        # P33b (B153 §3a): the converter's markdown announces itself on its
        # first line, so both routes mint the same kind for one workbook.
        doc_kind=("past_response" if text.startswith(PROVENANCE_PREFIX)
                  else "section_exemplar"),
    )
