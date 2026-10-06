"""A completed response workbook, rendered as the markdown the KB ingest
already reads (P33a, B151 §3c) — the converter half of the accelerator.

`pair_response_workbook` (engine/structure/response.py) says what the
workbook SAID; this module writes it in the one shape `read_source`'s
text path and `elements_from_markdown` consume: `#` the sheet, `##` a
section heading when the sheet has one, `###` the buyer's question, then
the firm's answer as its own lines. `chunk_elements` then makes exactly
one chunk per answered question, and `_candidates` titles the card with
the question (the deepest heading) and bodies it with the answer alone —
the owner's call (B151 §1c).

The markdown round-trip has one limit, stated and warned, never papered
over: an answer line that the reader would take for structure (a heading,
a comment, the `# DOC:` marker, a table row) is not rewritten — the pair
is refused with its address. The in-engine route (P33b, B153 §2:
`read_source`'s `.xlsx` branch) builds the elements HERE directly with
`elements_from_response`, so on that route such a line is plain text and
nothing is refused; its flat text is the lossless rendering.

The provenance comment carries the source digest and the parser version
and never the filename (P1-47: a file is named after its client). The
reader drops the comment line (`canonical.py`), so it reaches no card.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from engine.kb.canonical import Element
from engine.structure.response import (  # re-exported: the CLI's one import
    RESPONSE_PARSER_VERSION,
    ResponseWorkbook,
    ResponseWorkbookError,
    pair_response_workbook,
)

__all__ = ["DEGRADING_SKIPS", "PROVENANCE_PREFIX", "RESPONSE_PARSER_VERSION",
           "ResponseWorkbook", "ResponseWorkbookError", "RenderedMarkdown",
           "elements_from_response", "is_markdown_structural",
           "pair_response_workbook", "render_markdown"]

# The first line of every rendering — the reader's doc_kind cue (B153 §3a).
PROVENANCE_PREFIX = "<!-- response-workbook sha256:"
# Skip kinds that LOSE content the steward cannot see in the text — the
# read is degraded (still ingests, flagged). The pairing's other skips
# (unanswered, orphan, non-prose, pricing-shaped) are its rules, not a
# degradation (B153 §3e).
DEGRADING_SKIPS = frozenset({
    "hidden sheets", "hidden rows", "hidden answer columns",
    "formula answers without cache", "formula questions without cache",
})

# The reader's own structure rules (engine/kb/canonical.py:183-235): a
# heading, an HTML comment, the caller-script marker, a pipe-bounded row.
_HEADING = re.compile(r"^#{1,6} .+$")
_COMMENT = re.compile(r"^<!--.*-->$")
_MARKER = re.compile(r"^# DOC:\S+$")


def is_markdown_structural(line: str) -> bool:
    text = line.strip()
    if _HEADING.match(text) or _COMMENT.match(text) or _MARKER.match(text):
        return True
    return text.startswith("|") and text.endswith("|") and len(text) > 1


@dataclass
class RenderedMarkdown:
    text: str
    rendered: int  # pairs that reached the markdown
    warnings: list[str] = field(default_factory=list)


def render_markdown(book: ResponseWorkbook, *,
                    refuse_structural: bool = True) -> RenderedMarkdown:
    """`refuse_structural=False` is the in-engine route's lossless flat
    text (P33b) — never hand that text back to the markdown reader."""
    lines = [f"{PROVENANCE_PREFIX}{book.source_sha256[:12]} "
             f"parser:{book.parser_version} -->", ""]
    warnings: list[str] = []
    rendered = 0
    for sheet in book.sheets:
        name = sheet.name.strip()
        sheet_lines: list[str] = []
        for section in sheet.sections:
            section_lines: list[str] = []
            for pair in section.pairs:
                if refuse_structural and any(
                        is_markdown_structural(line) for line in pair.answer.splitlines()):
                    warnings.append(
                        f"{name}!row {pair.row}: answer skipped (markdown-structural line)")
                    continue
                section_lines.append(f"### {pair.question}")
                section_lines.append("")
                section_lines.extend(pair.answer.splitlines())
                section_lines.append("")
                rendered += 1
            if section_lines:
                if section.heading:
                    sheet_lines.extend([f"## {section.heading}", ""])
                sheet_lines.extend(section_lines)
        if sheet_lines:
            lines.extend([f"# {name}", ""])
            lines.extend(sheet_lines)
    text = "\n".join(lines).rstrip("\n") + "\n"
    return RenderedMarkdown(text=text, rendered=rendered, warnings=warnings)


def _answer_paragraphs(answer: str) -> list[str]:
    """The markdown reader's own grouping (canonical.py): lines stripped,
    a blank line ends a paragraph — so the two routes agree in shape."""
    paragraphs: list[str] = []
    run: list[str] = []
    for raw in answer.splitlines():
        line = raw.strip()
        if line:
            run.append(line)
        elif run:
            paragraphs.append("\n".join(run))
            run = []
    if run:
        paragraphs.append("\n".join(run))
    return paragraphs


def elements_from_response(book: ResponseWorkbook) -> list[Element]:
    """The in-engine route (P33b, B153 §2): the pairing straight into the
    canonical element list — `heading` 1 the sheet, 2 a section, 3 the
    buyer's question, the answer's paragraphs — the shape
    `elements_from_markdown` emits for `render_markdown`'s text, pinned by
    `tests/kb/test_canonical.py`. No `qa` element: P2-63's branch stays
    dormant (§3c)."""
    elements: list[Element] = []
    for sheet in book.sheets:
        elements.append(Element(kind="heading", text=sheet.name.strip(), level=1))
        for section in sheet.sections:
            if section.heading:
                elements.append(Element(kind="heading", text=section.heading.strip(),
                                        level=2))
            for pair in section.pairs:
                elements.append(Element(kind="heading", text=pair.question, level=3))
                for paragraph in _answer_paragraphs(pair.answer):
                    elements.append(Element(kind="paragraph", text=paragraph))
    return elements
