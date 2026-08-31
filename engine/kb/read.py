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
reader counts embedded images so ingest can flag the document (C11)."""

import importlib.metadata
import re
from dataclasses import dataclass, field
from pathlib import Path

from engine.extraction.fingerprint import stack_fingerprint
from engine.kb.canonical import Element, elements_from_markdown


@dataclass
class SourceText:
    text: str
    extractor: str  # "python-docx" | "text"
    fingerprint: str
    media: dict = field(default_factory=lambda: {"images": 0})
    elements: list = field(default_factory=list)  # list[canonical.Element]


def _docx_fingerprint() -> str:
    return stack_fingerprint(
        "python-docx",
        {"extractor_version": importlib.metadata.version("python-docx")},
    )


def _read_docx(path: Path) -> SourceText:
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    document = docx.Document(str(path))
    lines: list[str] = []
    elements: list[Element] = []
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
        elif isinstance(item, Table):
            for row in item.rows:
                texts = [c.text.replace("\n", " ") for c in row.cells
                         if c.text.strip()]
                if texts:
                    lines.append("| " + " | ".join(texts) + " |")
                    elements.append(Element(kind="table_row",
                                            text=" | ".join(texts)))
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


def read_source(path: Path) -> SourceText:
    """One source document -> text + stack identity + media facts."""
    path = Path(path)
    if path.suffix.lower() == ".docx":
        return _read_docx(path)
    text = path.read_text(encoding="utf-8")
    return SourceText(
        text=text,
        extractor="text",
        fingerprint=stack_fingerprint("text", {"extractor_version": "stdlib"}),
        elements=elements_from_markdown(text),
    )
