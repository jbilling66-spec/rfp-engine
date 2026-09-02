"""The buyer-DOCX parser (P16/C3, net-new — v1's standing refusal was
"buyer docx lands later"; this is later).

Two real shapes, one walk (conventions read from the pen corpus —
B73§1 — carried by the synthetic twins):

OUTLINE — numbered section headings ("1. Executive Summary", "2.1
Project Timeline") with instruction paragraphs beneath. Every numbered
heading is a mandated section: with instruction text it is an
answerable PROSE slot (the instructions are the ask); with only child
headings or attached tables it is a header slot. The numbering token
is the buyer's ref_id, preserved verbatim (never normalized). Stated
evaluation weights ("carries thirty percent (30%) of the evaluation
score") land in eval_weight; "(Optional)" / "may be omitted" writes
required: false (the schema default is true, so only the exception is
written); page limits become constraints (see below).

QUESTIONNAIRE — tables under the sections. A table whose first header
cell says "Question" yields one slot per row with an EMPTY answer cell
(a pre-filled row is the buyer's own example, not an ask); shapes come
from the xlsx trigger vocabulary (boolean/numeric/prose — one join,
one rulebook). A headered table whose data rows are ALL empty is a
buyer-defined grid: one table slot with typed per-column fields. A
filled table is furniture.

Page limits (B67-F6): constraints appear as PAGES, the coverage lane
measures WORDS. "shall not exceed two (2) pages" → max_words =
pages × WORDS_PER_PAGE (450 — a declared conversion, not a measure)
AND the verbatim rule in constraints.format, so the human always sees
what the buyer actually wrote.

Deterministic code end to end; zero model calls; slots shaped by the
frozen schema via the shared writers-omit discipline.
"""

import hashlib
import re
from pathlib import Path

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

from engine.contracts.slots import field_key
from engine.structure.classify import (
    _classify_shape,
    _field_type,
    _slot,
    _sub_questions,
)
from engine.structure.parse import ParsedWorkbook, StructureError
from engine.structure.zipguard import check_office_zip

WORDS_PER_PAGE = 450  # declared prose-page conversion (B67-F6)

_NUMBERED = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+(.+)$")
_HEADING_STYLE = re.compile(r"^Heading [1-9]$")
_OPTIONAL = re.compile(
    r"\(optional\)|\boptional\b.{0,40}\bomitted\b", re.IGNORECASE
)
_PAGE_LIMIT = re.compile(
    r"(?:shall not|must not|should not|not to)\s+exceed\s+"
    r"(?:[a-z\- ]+)?\((\d{1,3})\)\s*pages?"
    r"|limited to\s+(\d{1,3})\s+pages?"
    r"|page limit of\s+(\d{1,3})"
    r"|maximum of\s+(\d{1,3})\s+pages?",
    re.IGNORECASE,
)
_WEIGHT = re.compile(
    r"\((\d{1,3}(?:\.\d+)?)\s*%\)[^.]{0,60}?"
    r"(?:evaluation|score|weight|points)"
    r"|(?:evaluation|score|weight)[^.]{0,60}?"
    r"\((\d{1,3}(?:\.\d+)?)\s*%\)"
    r"|weight(?:ed at|:)\s*(\d{1,3}(?:\.\d+)?)\s*%",
    re.IGNORECASE,
)


def _depth(ref: str) -> int:
    return ref.count(".") + 1


def _page_constraints(text: str) -> dict | None:
    m = _PAGE_LIMIT.search(text)
    if not m:
        return None
    pages = int(next(g for g in m.groups() if g))
    return {"max_words": pages * WORDS_PER_PAGE,
            "format": m.group(0).strip()}


def _stated_weight(text: str) -> float | None:
    m = _WEIGHT.search(text)
    if not m:
        return None
    value = float(next(g for g in m.groups() if g))
    return int(value) if value == int(value) else value


def _events(document):
    for child in document.element.body.iterchildren():
        if child.tag.endswith("}p"):
            para = Paragraph(child, document)
            style = para.style.name if para.style is not None else ""
            text = para.text.strip()
            if text:
                yield ("heading" if _HEADING_STYLE.match(style) else "para",
                       text)
        elif child.tag.endswith("}tbl"):
            yield ("table", Table(child, document))


def _question_table_slots(table, table_index: int, section) -> list[dict]:
    """One slot per open Question|Response row; pre-filled rows are the
    buyer's own examples, never asks."""
    header = [c.text.strip() for c in table.rows[0].cells]
    answer_col = len(header) - 1
    slots = []
    for r, row in enumerate(table.rows[1:], start=1):
        question = row.cells[0].text.strip()
        answer = row.cells[answer_col].text.strip()
        if not question or answer:
            continue
        slots.append(_slot(
            slot_id=f"s-t{table_index:02d}-r{r:02d}",
            source_mode="client_provided",
            # The frozen slot-level locator vocabulary is {file, sheet,
            # cell, docx_anchor}; the table/row/column address is NOT
            # persisted — it is re-derived from the digest-bound source
            # by question_cell_map() at write-back time (the server
            # re-derives, never trusts an echo).
            source_locator={
                "docx_anchor": section["anchor"] if section else "",
            },
            path=(f"{section['title']} > {question[:40]}"
                  if section else question[:40]),
            parent=section["slot_id"] if section else None,
            question_text=question,
            sub_questions=_sub_questions(question),
            response_shape=_classify_shape(question),
        ))
    return slots


def _grid_slot(table, table_index: int, section) -> dict | None:
    header = [c.text.strip() for c in table.rows[0].cells]
    if not all(header) or len(table.rows) < 2:
        return None
    body_cells = [c.text.strip() for row in table.rows[1:]
                  for c in row.cells]
    if any(body_cells):
        return None  # a filled table is the buyer's content, not an ask
    return _slot(
        slot_id=f"s-t{table_index:02d}",
        source_mode="client_provided",
        source_locator={
            "docx_anchor": section["anchor"] if section else "",
        },
        path=section["title"] if section else "Buyer grid",
        parent=section["slot_id"] if section else None,
        question_text=(f"Complete the buyer-defined grid: "
                       f"{', '.join(header)}"),
        response_shape="table",
        fill_type="template_fill",
        response_fields=[
            {"key": key, "label": label, "type": _field_type(label),
             "source_locator": {"table_index": table_index, "column": i}}
            for i, (key, label) in enumerate(
                zip((field_key(h) for h in header), header))
        ],
    )


def _fillin_slot(table, table_index: int, anchor: str,
                 parent: str | None) -> dict | None:
    """B67-F3: a fill-in table — some columns fully FILLED (the buyer's
    labels: roles, phases, line items), some fully EMPTY (the asks) —
    is a response target embedded in the document. One template_fill
    slot; fields are the empty columns. A fully-filled table is buyer
    content; a fully-empty one is _grid_slot's case."""
    if not table.rows or len(table.rows) < 2:
        return None
    header = [c.text.strip() for c in table.rows[0].cells]
    if not all(header):
        return None
    body = [[c.text.strip() for c in row.cells] for row in table.rows[1:]]
    filled_cols = [i for i in range(len(header))
                   if all(row[i] for row in body)]
    empty_cols = [i for i in range(len(header))
                  if all(not row[i] for row in body)]
    if not filled_cols or not empty_cols:
        return None
    if len(filled_cols) + len(empty_cols) != len(header):
        return None  # partially-answered columns: not a clean fill-in ask
    return _slot(
        slot_id=f"s-t{table_index:02d}",
        source_mode="client_provided",
        source_locator={"docx_anchor": anchor},
        path=f"Fill-in table: {header[0]}",
        parent=parent,
        question_text=(
            "Complete the fill-in table (" + ", ".join(header) + ") — "
            + "; ".join(f"per {header[i]}" for i in filled_cols)),
        response_shape="table",
        fill_type="template_fill",
        response_fields=[
            {"key": field_key(header[i]), "label": header[i],
             "type": _field_type(header[i]),
             "source_locator": {"table_index": table_index, "column": i}}
            for i in empty_cols
        ],
    )


def _table_slots_for(table, t_index: int, section: dict | None,
                     anchor: str, parent: str | None) -> list[dict]:
    """Classification order: question table → empty grid → fill-in."""
    header_first = (table.rows[0].cells[0].text.strip().lower()
                    if table.rows else "")
    if header_first == "question" and len(table.columns) >= 2:
        found = _question_table_slots(table, t_index, section)
    else:
        grid = _grid_slot(table, t_index, section)
        if grid:
            found = [grid]
        else:
            fillin = _fillin_slot(table, t_index, anchor, parent)
            found = [fillin] if fillin else []
    for slot in found:  # orphans anchor to their nearest heading
        if not slot["source_locator"].get("docx_anchor"):
            slot["source_locator"]["docx_anchor"] = anchor
    return found


def parse_buyer_docx(path: Path, *, core_scan: bool = False) -> ParsedWorkbook:
    """core_scan=False: a DECLARED target — zero answerable slots is a
    loud StructureError, never a silent free_flow. core_scan=True: an
    opportunistic sweep of a CORE narrative document (B67-F3) — finding
    nothing is a normal outcome and returns an empty parse."""
    from engine.structure import DOCX_PARSER_VERSION

    path = Path(path)
    if not path.is_file():
        raise StructureError(f"no document at {path}")
    check_office_zip(path)  # P0-8: the container before the parser
    document = Document(str(path))

    # Pass 1: sections from numbered headings; paragraphs and tables
    # attach to the section they follow. Tables OUTSIDE any numbered
    # section (a form document without headings, a fill-in table under
    # a prose heading) are kept as orphans with their nearest heading
    # as anchor.
    sections: list[dict] = []
    orphans: list[tuple[int, object, str]] = []
    current: dict | None = None
    last_heading = ""
    table_index = -1
    for kind, payload in _events(document):
        if kind == "heading":
            last_heading = payload
            m = _NUMBERED.match(payload)
            if not m:
                current = None  # un-numbered headings are furniture
                continue
            ref, title = m.group(1), m.group(2).strip()
            current = {
                "ref": ref, "title": title, "anchor": payload,
                "slot_id": f"s-r{ref.replace('.', '_')}",
                "texts": [], "tables": [],
            }
            sections.append(current)
        elif kind == "para":
            if current is not None:
                current["texts"].append(payload)
        else:
            table_index += 1
            if current is not None:
                current["tables"].append((table_index, payload))
            else:
                orphans.append((table_index, payload, last_heading))

    # Duplicate buyer numbering is preserved on ref_id, never "fixed" —
    # but slot ids must stay unique.
    seen: dict[str, int] = {}
    for section in sections:
        n = seen.get(section["slot_id"], 0)
        seen[section["slot_id"]] = n + 1
        if n:
            section["slot_id"] = f"{section['slot_id']}-{n + 1}"

    slots: list[dict] = []
    for i, section in enumerate(sections):
        has_children = (i + 1 < len(sections)
                        and _depth(sections[i + 1]["ref"])
                        > _depth(section["ref"]))
        parent = next(
            (s["slot_id"] for s in reversed(sections[:i])
             if _depth(s["ref"]) < _depth(section["ref"])), None)
        instructions = " ".join(section["texts"]).strip()
        table_slots: list[dict] = []
        for t_index, table in section["tables"]:
            table_slots.extend(_table_slots_for(
                table, t_index, section, section["anchor"],
                section["slot_id"]))

        header_only = bool(table_slots) or (has_children and not instructions)
        if header_only:
            slots.append(_slot(
                slot_id=section["slot_id"],
                ref_id=section["ref"],
                source_mode="client_provided",
                source_locator={"file": path.name,
                                "docx_anchor": section["anchor"]},
                path=section["title"],
                parent=parent,
                is_header=True,
                question_text=section["title"],
                response_shape="none",
            ))
        else:
            ask = instructions or section["title"]
            constraints = _page_constraints(ask)
            weight = _stated_weight(ask)
            optional = bool(_OPTIONAL.search(section["title"])
                            or _OPTIONAL.search(ask))
            slots.append(_slot(
                slot_id=section["slot_id"],
                ref_id=section["ref"],
                source_mode="client_provided",
                source_locator={"file": path.name,
                                "docx_anchor": section["anchor"]},
                path=section["title"],
                parent=parent,
                question_text=ask,
                sub_questions=_sub_questions(ask),
                eval_weight=weight,
                required=False if optional else None,  # default true, omitted
                response_shape=_classify_shape(ask),
                constraints=constraints,
            ))
        for slot in table_slots:
            slot["source_locator"]["file"] = path.name
        slots.extend(table_slots)

    for t_index, table, anchor in orphans:
        for slot in _table_slots_for(table, t_index, None, anchor, None):
            slot["source_locator"]["file"] = path.name
            slots.append(slot)

    if not core_scan and not any(not s.get("is_header") for s in slots):
        raise StructureError(
            f"{path.name}: no answerable slots parsed — not a recognizable "
            "buyer outline or questionnaire (loud, never free_flow)"
        )

    return ParsedWorkbook(
        file=path.name,
        source_mode="client_provided",
        parser_version=DOCX_PARSER_VERSION,
        source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        slots=slots,
    )


def question_cell_map(path: Path) -> dict[str, dict]:
    """slot_id -> {table_index, row, column} for every question-table
    slot in the document. The frozen slot schema does not carry table
    addresses, so write-back RE-DERIVES them from the digest-bound
    source file — deterministic parse, same ids, server-side truth."""
    check_office_zip(path)  # P0-8: the container before the parser
    document = Document(str(Path(path)))
    cells: dict[str, dict] = {}
    table_index = -1
    for kind, payload in _events(document):
        if kind != "table":
            continue
        table_index += 1
        table = payload
        first = (table.rows[0].cells[0].text.strip().lower()
                 if table.rows else "")
        if first != "question" or len(table.columns) < 2:
            continue
        answer_col = len(table.rows[0].cells) - 1
        for r, row in enumerate(table.rows[1:], start=1):
            if not row.cells[0].text.strip() or (
                    row.cells[answer_col].text.strip()):
                continue
            cells[f"s-t{table_index:02d}-r{r:02d}"] = {
                "table_index": table_index, "row": r, "column": answer_col,
            }
    return cells
