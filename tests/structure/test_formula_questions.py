"""P1-24 (P26b-1, B112, the owner's call): a buyer question authored as a
formula parses from the CACHED value the writer saved; a file with no
cache warns instead. Expectations are hand-derived from
`tests/fixtures/twins.py`: the formula twin is the structured twin plus a
ref in A6 of sheet 2 and a spliced cached value for B6 — the text of
sheet 1's B2 — so it parses to the structured twin's 8 slots plus one.
"""

from pathlib import Path

from engine.structure import PARSER_VERSION, parse_workbook
from engine.structure.facts import collect_workbook_facts
from tests.fixtures.twins import B6_CACHED

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_parser_version_is_the_p26b_bump():
    assert PARSER_VERSION == "2.1.0"


def test_formula_twin_emits_the_slot_from_the_cached_value():
    parsed = parse_workbook(FIXTURES / "formula-twin.xlsx")
    assert parsed.slot_count == 9
    slot = next(s for s in parsed.slots if s["ref_id"] == "2.0.9")
    assert slot["question_text"] == B6_CACHED
    assert slot["source_locator"]["cell"] == "C6"  # the answer cell, not B6
    assert not any("row 6" in w for w in parsed.warnings)
    assert parsed.parser_version == "2.1.0"


def test_the_fact_keeps_the_formula_source_beside_the_cache():
    facts = collect_workbook_facts(FIXTURES / "formula-twin.xlsx")
    sheet = next(s for s in facts.sheets if s.name == "2. Integration ")
    fact = sheet.cells["B6"]
    assert fact.is_formula and fact.formula == "='1. Company Background'!B2"
    assert fact.cached_text == B6_CACHED and fact.text == B6_CACHED


def test_structured_twin_without_a_cache_warns_and_emits_nothing():
    parsed = parse_workbook(FIXTURES / "structured-twin.xlsx")
    assert parsed.slot_count == 8
    assert ("2. Integration!row 6: formula-only row skipped (a formula "
            "question needs a cached value)") in parsed.warnings
    sheet = next(s for s in collect_workbook_facts(FIXTURES / "structured-twin.xlsx").sheets
                 if s.name == "2. Integration ")
    assert sheet.cells["B6"].cached_text is None


def test_a_formula_in_the_answer_column_is_never_an_answer():
    # Sheet 3's =SUM total keeps its cache-less formula status and stays
    # out of the grid in both twins (EC-5b).
    for name in ("formula-twin.xlsx", "structured-twin.xlsx"):
        parsed = parse_workbook(FIXTURES / name)
        assert not any(s["source_locator"].get("cell") == "B5" for s in parsed.slots)
