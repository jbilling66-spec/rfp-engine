"""Global-constraint extraction — the two places rules hide.

Real buyers state rules in an Instructions tab ("avoid lengthy
narrative", the subpoint mandate) AND in footnotes at the bottom of
grids ("** No Offshore resources are allowed"). Both become constraint
dicts: Instructions rules stamp every non-header slot and are recorded
once in the container meta; a footnote scopes to its own sheet's slots.

CONSTRAINT_PATTERNS is the documented rule table (v1 oracle, evidence-
led — every pattern fired on a real file): pattern order is the
canonical flag order, so stamping is deterministic. Length caps are a
separate table because they capture a NUMBER; the stated number must
sit next to a limiting verb — "our 150 words of guidance" is prose,
and a cap stamped off it would silently truncate answers nobody asked
to shorten.
"""

import re
from dataclasses import dataclass

from engine.structure.facts import SheetFacts


@dataclass(frozen=True)
class ConstraintPattern:
    pattern: re.Pattern
    brevity: str | None = None
    format: str | None = None
    flag: str | None = None


CONSTRAINT_PATTERNS: tuple[ConstraintPattern, ...] = (
    ConstraintPattern(re.compile(r"avoid lengthy narrative", re.I), brevity="terse"),
    ConstraintPattern(re.compile(r"blue answer cells", re.I), format="blue_cells_only"),
    ConstraintPattern(
        re.compile(r"do not place all information in one cell|subpoint structure", re.I),
        flag="subpoint_granularity",
    ),
    ConstraintPattern(
        re.compile(r"case stud(?:y|ies).{0,40}appendix", re.I),
        flag="case_studies_to_appendix",
    ),
    ConstraintPattern(re.compile(r"as a separate appendix", re.I), flag="appendix_routing"),
    ConstraintPattern(
        re.compile(r"(?:state|indicate).{0,30}not offered|if not offered", re.I),
        flag="state_if_not_offered",
    ),
    ConstraintPattern(
        re.compile(r"partners? deliver", re.I), flag="disclose_partner_delivery"
    ),
    ConstraintPattern(re.compile(r"no offshore", re.I), flag="no_offshore"),
)

_LIMIT_LEAD = (
    r"(?:limit(?:ed)?|maximum|max\.?|no more than|not exceed|"
    r"up to|within|at most|under)"
)
LENGTH_PATTERNS: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(rf"{_LIMIT_LEAD}[^.\n]{{0,40}}?(\d[\d,]*)\s*words?", re.I),
     "max_words"),
    (re.compile(rf"{_LIMIT_LEAD}[^.\n]{{0,40}}?(\d[\d,]*)\s*characters?", re.I),
     "max_chars"),
)


def _length_limits(text: str) -> dict[str, int]:
    """The stated caps, smallest wins (a global instruction and a tighter
    per-section note can both appear; the BINDING one is the smaller)."""
    found: dict[str, int] = {}
    for pattern, key in LENGTH_PATTERNS:
        for match in pattern.finditer(text):
            value = int(match.group(1).replace(",", ""))
            if value > 0 and (key not in found or value < found[key]):
                found[key] = value
    return found


def _match_lines(lines: list[str]) -> dict | None:
    out: dict = {}
    flags: list[str] = []
    text = "\n".join(lines)
    for rule in CONSTRAINT_PATTERNS:
        if not rule.pattern.search(text):
            continue
        if rule.brevity is not None:
            out.setdefault("brevity", rule.brevity)
        if rule.format is not None:
            out.setdefault("format", rule.format)
        if rule.flag is not None and rule.flag not in flags:
            flags.append(rule.flag)
    if flags:
        out["flags"] = flags
    out.update(_length_limits(text))
    return out or None


def extract_global_constraints(sheet: SheetFacts) -> dict | None:
    """Digest an Instructions sheet into one global constraint dict."""
    lines = [f.text for f in sheet.cells.values() if f.text and not f.is_formula]
    return _match_lines(lines)


def extract_footnotes(sheet: SheetFacts, below_row: int) -> dict | None:
    """Constraints hiding below a grid: *-prefixed text rows after the
    sheet's last answer-bearing row."""
    lines = [
        f.text
        for f in sheet.cells.values()
        if f.text and not f.is_formula
        and f.row > below_row
        and f.text.lstrip().startswith("*")
    ]
    return _match_lines(lines) if lines else None


def merge_constraints(base: dict | None, extra: dict) -> dict:
    """Merge: first-wins for brevity/format, union for flags, TIGHTEST
    wins for length caps (a sheet footnote saying 100 words under a
    global 150 binds at 100)."""
    if base is None:
        merged: dict = {}
    else:
        merged = {k: (list(v) if isinstance(v, list) else v) for k, v in base.items()}
    merged.setdefault("brevity", extra.get("brevity"))
    merged.setdefault("format", extra.get("format"))
    flags = merged.get("flags", [])
    for flag in extra.get("flags", []):
        if flag not in flags:
            flags.append(flag)
    if flags:
        merged["flags"] = flags
    for key in ("max_words", "max_chars"):
        mine, theirs = merged.get(key), extra.get(key)
        if theirs is not None and (mine is None or theirs < mine):
            merged[key] = theirs
    return {k: v for k, v in merged.items() if v is not None}


def apply_constraints(
    slots: list[dict],
    global_constraints: dict | None,
    per_sheet: dict[str, dict],
) -> None:
    """Stamp global constraints on every non-header slot and sheet-scoped
    footnote constraints on that sheet's slots. Header slots carry none."""
    for slot in slots:
        if slot.get("is_header"):
            continue
        sheet = slot.get("source_locator", {}).get("sheet")
        footnote = per_sheet.get(sheet) if sheet else None
        if global_constraints is not None:
            slot["constraints"] = merge_constraints(
                slot.get("constraints"), global_constraints
            )
        if footnote is not None:
            slot["constraints"] = merge_constraints(slot.get("constraints"), footnote)
