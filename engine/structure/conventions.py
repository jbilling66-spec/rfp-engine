"""Layer 2 — learned per-workbook conventions.

Decides what THIS workbook means by its facts: which fill marks a
writable answer cell (when the workbook uses fills at all), which
column carries the buyer's ref numbering, which column holds answers,
where column-header label rows sit.

The unified answer-column model (v1 oracle, learned from real files):
on a questions sheet the ANSWER COLUMN is the convention — every leaf
row's answer cell lives there whether empty-with-writable-fill, carrying
buyer DIRECTIVE text, or entirely absent. Fills describe writability
FACTS; they never decide slot existence.

The EC-3 fix, carried and extended: leaf depth is voted by ref rows that
LOOK answerable — in fill mode, rows carrying an answer cell; in
structural mode (no fills anywhere), every dotted-ref row with
question-length text votes. v1's bug was requiring a fill in both arms,
so a no-fill workbook numbered "1.1" parsed to ZERO slots silently.
"""

import re
from collections import Counter
from dataclasses import dataclass, field

from openpyxl.utils import column_index_from_string

from engine.structure.facts import CellFact, SheetFacts, WorkbookFacts

REF = re.compile(r"^\d+(\.\d+)*$")

_SHORT_LABEL = 60
_LABEL_MAX = 110
QUESTION_LEN = 20


@dataclass
class SheetConventions:
    ref_col: int | None = None
    leaf_depth: int = 3
    question_col: int | None = None
    answer_col: int | None = None
    # label rows: row -> ordered (col, label); validity resets at header slots
    label_rows: dict[int, list[tuple[int, str]]] = field(default_factory=dict)
    first_label_row: int | None = None
    kind: str = "questions"  # instructions | questions | grid


@dataclass
class Conventions:
    writable_fill: str | None = None
    header_fills: set[str] = field(default_factory=set)
    legend_source: str = "dominant"  # "dominant" | "structural"
    sheets: dict[str, SheetConventions] = field(default_factory=dict)


def depth(ref: str) -> int:
    return ref.count(".") + 1


def row_ref(row_facts: list[CellFact], ref_col: int | None) -> str | None:
    """The buyer's own ref id on this row, if the sheet has a ref column.
    ONE implementation — Layer 2 (while voting) and Layer 3 (while
    classifying) must agree about which cell is a row's identity."""
    if ref_col is None:
        return None
    return next(
        (f.text.strip() for f in row_facts
         if f.col == ref_col and f.text and not f.is_formula
         and REF.match(f.text.strip())),
        None,
    )


def is_instructions(sheet: SheetFacts) -> bool:
    return "instruction" in sheet.name.lower()


def merged_member_cols_by_row(sheet: SheetFacts) -> dict[int, set[int]]:
    """Row -> columns occupied by merged-range MEMBERS (anchor excluded):
    those cells belong to a forward-filled value, never to an answer."""
    out: dict[int, set[int]] = {}
    for rng in sheet.merged_ranges:
        m = re.match(r"^([A-Z]+)(\d+):([A-Z]+)(\d+)$", rng)
        if not m:
            continue
        c1, r1 = column_index_from_string(m.group(1)), int(m.group(2))
        c2, r2 = column_index_from_string(m.group(3)), int(m.group(4))
        for row in range(r1, r2 + 1):
            for col in range(c1, c2 + 1):
                if row == r1 and col == c1:
                    continue  # the anchor may legitimately be an answer
                out.setdefault(row, set()).add(col)
    return out


def answer_cells(
    row_facts: list[CellFact],
    sc: SheetConventions,
    conv: Conventions,
    row_num: int | None = None,
    merged_member_cols: set[int] | None = None,
) -> list[CellFact]:
    """The row's answer cells. Fill mode: empty writable-fill cells.
    Structural mode: labeled columns with NO fact in this row are
    truly-empty answer cells, SYNTHESIZED here (a cell with neither
    value nor fill is never collected as a fact). Rows whose labeled
    column holds a formula (grid TOTAL rows) or whose only text is a
    *-footnote yield no answers; merged members never qualify."""
    if conv.writable_fill is not None:
        return [
            f for f in row_facts
            if f.text is None and f.fill == conv.writable_fill and not f.is_formula
        ]
    if row_num is None or sc.first_label_row is None or row_num <= sc.first_label_row:
        return []
    labeled_cols: set[int] = set()
    for cols in sc.label_rows.values():
        labeled_cols.update(c for c, _ in cols)
    texts = [f for f in row_facts if f.text and not f.is_formula]
    if not texts:
        return []  # fully-empty rows are spacing, not answer rows
    if all(f.text.lstrip().startswith("*") for f in texts):
        return []  # footnote row
    if any(f.is_formula and f.col in labeled_cols for f in row_facts):
        return []  # grid TOTAL row — formulas are facts, never targets
    from openpyxl.utils import get_column_letter

    occupied = {f.col for f in row_facts}
    blocked = merged_member_cols or set()
    return [
        CellFact(cell=f"{get_column_letter(col)}{row_num}", row=row_num, col=col,
                 text=None, fill=None, is_formula=False, formula=None,
                 merged_range=None, bold=False)
        for col in sorted(labeled_cols - occupied - blocked)
    ]


def learn_conventions(facts: WorkbookFacts) -> Conventions:
    conv = Conventions()

    # Writable fill: dominant fill among EMPTY cells sitting in rows that
    # also carry question-length text.
    votes: Counter[str] = Counter()
    for sheet in facts.sheets:
        if is_instructions(sheet):
            continue
        for row_facts in sheet.rows().values():
            has_text = any(
                f.text and not f.is_formula and len(f.text) >= QUESTION_LEN
                for f in row_facts
            )
            if not has_text:
                continue
            for f in row_facts:
                if f.text is None and f.fill is not None:
                    votes[f.fill] += 1
    if votes:
        conv.writable_fill = votes.most_common(1)[0][0]
    else:
        conv.legend_source = "structural"  # the no-fill workbook

    # Header fills: fills on rows of >=2 short labels with no empty
    # writable cell.
    if conv.writable_fill is not None:
        for sheet in facts.sheets:
            if is_instructions(sheet):
                continue
            for row_facts in sheet.rows().values():
                labels = [
                    f for f in row_facts
                    if f.text and not f.is_formula and len(f.text) <= _SHORT_LABEL
                ]
                empties = [
                    f for f in row_facts
                    if f.text is None and f.fill == conv.writable_fill
                ]
                if len(labels) >= 2 and not empties:
                    for f in labels:
                        if f.fill and f.fill != conv.writable_fill:
                            conv.header_fills.add(f.fill)

    for sheet in facts.sheets:
        conv.sheets[sheet.name] = _learn_sheet(sheet, conv)
    return conv


def _learn_sheet(sheet: SheetFacts, conv: Conventions) -> SheetConventions:
    sc = SheetConventions()
    if is_instructions(sheet):
        sc.kind = "instructions"
        return sc

    rows = sheet.rows()

    # Ref column: established only by DOTTED values (bare integers — grid
    # phase numbers — never establish one).
    ref_votes: Counter[int] = Counter()
    for row_facts in rows.values():
        for f in row_facts:
            if (
                f.text and not f.is_formula
                and REF.match(f.text.strip()) and "." in f.text
            ):
                ref_votes[f.col] += 1
    if ref_votes:
        sc.ref_col = ref_votes.most_common(1)[0][0]

    # Label rows. Fill mode WITH learned header fills: >=2 short labels
    # wearing a header fill, no empty writable cell. Otherwise (no header
    # fills learned, or structural mode) the bare-header rule: >=2 short
    # LETTERED labels outside the ref column with nothing longer in the
    # row — the twins' unstyled "Ref | Question | Response" headers are
    # label rows too, or Rule 4 would slot them. A bare number ("400")
    # is data, never a label: without the letter requirement a grid's
    # value rows ("Discover | 400") would masquerade as label rows and
    # swallow the grid.
    label_cap = _LABEL_MAX if conv.header_fills else _SHORT_LABEL
    bare_mode = not conv.header_fills
    for row_num, row_facts in sorted(rows.items()):
        labels = [
            f for f in row_facts
            if f.text and not f.is_formula and len(f.text) <= label_cap
            and f.col != sc.ref_col
            and (not bare_mode or any(c.isalpha() for c in f.text))
        ]
        if len(labels) < 2:
            continue
        if conv.writable_fill is not None:
            empties = [
                f for f in row_facts
                if f.text is None and f.fill == conv.writable_fill
            ]
            if empties:
                continue
            if conv.header_fills and not any(
                f.fill in conv.header_fills for f in labels
            ):
                continue
            if not conv.header_fills:
                long_text = [
                    f for f in row_facts
                    if f.text and not f.is_formula and len(f.text) > label_cap
                ]
                if long_text:
                    continue
        else:
            long_text = [
                f for f in row_facts
                if f.text and not f.is_formula and len(f.text) > label_cap
            ]
            if long_text:
                continue
        sc.label_rows[row_num] = [
            (f.col, f.text.strip()) for f in labels
        ]
        if sc.first_label_row is None:
            sc.first_label_row = row_num

    # Question column: the column with the most question-length text.
    q_votes: Counter[int] = Counter()
    for row_facts in rows.values():
        for f in row_facts:
            if (
                f.text and not f.is_formula and len(f.text) >= QUESTION_LEN
                and f.col != sc.ref_col
            ):
                q_votes[f.col] += 1
    if q_votes:
        sc.question_col = q_votes.most_common(1)[0][0]

    # Answer column. Fill mode: modal column of empty writable-fill
    # cells. Structural mode: the /response|answer/i-labeled column of
    # the first label row; else question_col + 1.
    if conv.writable_fill is not None:
        a_votes: Counter[int] = Counter()
        for row_facts in rows.values():
            for f in row_facts:
                if f.text is None and f.fill == conv.writable_fill:
                    a_votes[f.col] += 1
        if a_votes:
            sc.answer_col = a_votes.most_common(1)[0][0]
    if sc.answer_col is None and sc.first_label_row is not None:
        for col, label in sc.label_rows[sc.first_label_row]:
            if re.search(r"\bresponse|\banswer", label, re.IGNORECASE):
                sc.answer_col = col
                break
    if sc.answer_col is None and sc.question_col is not None:
        sc.answer_col = sc.question_col + 1

    # Leaf depth: modal ref depth on rows that LOOK answerable — fill
    # mode: rows carrying an answer cell; structural mode: dotted-ref
    # rows with question-length text (the EC-3 fix's v2 extension: a
    # no-fill, no-response-column form still votes).
    if sc.ref_col is not None:
        depths: Counter[int] = Counter()
        members = merged_member_cols_by_row(sheet)
        for row_num, row_facts in rows.items():
            ref = row_ref(row_facts, sc.ref_col)
            if not ref:
                continue
            if conv.writable_fill is not None:
                if answer_cells(row_facts, sc, conv, row_num, members.get(row_num)):
                    depths[depth(ref)] += 1
            else:
                has_question = any(
                    f.text and not f.is_formula and len(f.text) >= QUESTION_LEN
                    and f.col != sc.ref_col
                    for f in row_facts
                )
                if has_question:
                    depths[depth(ref)] += 1
        if depths:
            sc.leaf_depth = max(depths.most_common(1)[0][0], 2)

    # Sheet kind: ref-less sheets with a label row whose data rows put
    # values (or answer cells) in >=2 labeled columns are grids. The
    # value branch is a v2 extension: the synthetic pricing grid carries
    # pre-filled scaffolding values rather than writable fills (B28).
    if sc.ref_col is None and sc.first_label_row is not None:
        labeled_cols = {c for cols in sc.label_rows.values() for c, _ in cols}
        members = merged_member_cols_by_row(sheet)
        data_multi = 0
        for row_num, row_facts in rows.items():
            if row_num <= sc.first_label_row:
                continue
            answers = answer_cells(row_facts, sc, conv, row_num, members.get(row_num))
            values = [
                f for f in row_facts
                if f.text and not f.is_formula and f.col in labeled_cols
            ]
            if len(answers) >= 2 or len(values) >= 2:
                data_multi += 1
        if data_multi >= 1:
            sc.kind = "grid"
    return sc
