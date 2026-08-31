"""Instructions-tab and footnote constraint extraction (EC-7) plus the
merge discipline. The footnote mechanism is tested on synthetic sheets
because no committed twin states a footnote the pattern table matches —
inventing one on a twin would be a constraint nobody's file stated."""

from pathlib import Path

from engine.structure.facts import CellFact, SheetFacts
from engine.structure.instructions import (
    extract_footnotes,
    extract_global_constraints,
    merge_constraints,
)
from engine.structure.parse import parse_workbook

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _sheet(rows: list[tuple[int, str]]) -> SheetFacts:
    sheet = SheetFacts(name="S", index=0)
    for row, text in rows:
        sheet.cells[f"A{row}"] = CellFact(
            cell=f"A{row}", row=row, col=1, text=text, fill=None,
            is_formula=False, formula=None, merged_range=None, bold=False,
        )
    return sheet


def test_structured_twin_stamps_the_250_word_limit_on_every_leaf():
    parsed = parse_workbook(FIXTURES / "structured-twin.xlsx")
    assert parsed.global_constraints == {"max_words": 250}
    for slot in parsed.slots:
        if not slot.get("is_header"):
            assert slot["constraints"]["max_words"] == 250


def test_constraint_patterns_extract_flags_and_brevity():
    sheet = _sheet([
        (1, "Avoid lengthy narrative. Use the blue answer cells only."),
        (2, "Please state if a service is not offered."),
        (3, "Identify where partners deliver any portion of the work."),
    ])
    got = extract_global_constraints(sheet)
    assert got == {
        "brevity": "terse",
        "format": "blue_cells_only",
        "flags": ["state_if_not_offered", "disclose_partner_delivery"],
    }


def test_length_limit_requires_a_limiting_verb():
    # "our 150 words of guidance" is prose, not a rule — stamping a cap
    # off it would silently truncate answers nobody asked to shorten.
    assert extract_global_constraints(_sheet([(1, "our 150 words of guidance")])) is None
    got = extract_global_constraints(_sheet([(1, "Responses must not exceed 150 words.")]))
    assert got == {"max_words": 150}


def test_footnotes_scope_below_the_last_answer_row():
    sheet = _sheet([
        (2, "Describe your delivery approach for this engagement."),
        (9, "** No Offshore resources are allowed."),
    ])
    assert extract_footnotes(sheet, below_row=2) == {"flags": ["no_offshore"]}
    # The same line ABOVE the answer rows is instructions prose, not a
    # footnote — proves the scoping is real, not a whole-sheet grep.
    assert extract_footnotes(sheet, below_row=9) is None


def test_merge_takes_the_tightest_length_cap():
    merged = merge_constraints(
        {"max_words": 150, "flags": ["no_offshore"]},
        {"max_words": 100, "brevity": "terse", "flags": ["appendix_routing"]},
    )
    assert merged == {
        "max_words": 100,
        "brevity": "terse",
        "flags": ["no_offshore", "appendix_routing"],
    }
