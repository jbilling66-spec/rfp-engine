"""parse_workbook — the Path-A entry point: buyer xlsx -> TargetSlot dicts.

Deterministic code end to end; zero model calls (B28 roster deviation —
a scripted fake "parse" would be fiction). Every produced slot is
schema-shaped for the frozen target-slot contract; the caller validates
(the planning stage does, before writing slots.json).
"""

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from engine.structure.classify import link_gating, parse_sheet
from engine.structure.conventions import is_instructions, learn_conventions
from engine.structure.facts import collect_workbook_facts
from engine.structure.instructions import (
    apply_constraints,
    extract_footnotes,
    extract_global_constraints,
)


class StructureError(ValueError):
    """A workbook could not be parsed as a designated structure."""


@dataclass
class ParsedWorkbook:
    file: str
    source_mode: str
    parser_version: str
    source_sha256: str
    slots: list[dict] = field(default_factory=list)
    global_constraints: dict | None = None

    @property
    def slot_count(self) -> int:
        return len(self.slots)


def parse_workbook(path: Path) -> ParsedWorkbook:
    from engine.structure import PARSER_VERSION

    path = Path(path)
    if not path.is_file():
        raise StructureError(f"no workbook at {path}")
    facts = collect_workbook_facts(path)
    conv = learn_conventions(facts)

    slots: list[dict] = []
    last_answer_row: dict[str, int] = {}
    for sheet in facts.sheets:
        sheet_slots = parse_sheet(sheet, conv.sheets[sheet.name], conv, facts.file)
        slots.extend(sheet_slots)
        rows = [
            int(m.group(1))
            for s in sheet_slots
            if (cell := s.get("source_locator", {}).get("cell"))
            and (m := re.match(r"^[A-Z]+(\d+)$", cell))
        ]
        last_answer_row[sheet.name] = max(rows, default=0)

    link_gating(slots)

    global_constraints = None
    instructions_sheet = next((s for s in facts.sheets if is_instructions(s)), None)
    if instructions_sheet is not None:
        global_constraints = extract_global_constraints(instructions_sheet)
    per_sheet: dict[str, dict] = {}
    for sheet in facts.sheets:
        footnote = extract_footnotes(sheet, last_answer_row.get(sheet.name, 0))
        if footnote is not None:
            per_sheet[sheet.name] = footnote
    apply_constraints(slots, global_constraints, per_sheet)

    return ParsedWorkbook(
        file=facts.file,
        source_mode="client_provided",
        parser_version=PARSER_VERSION,
        source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        slots=slots,
        global_constraints=global_constraints,
    )
