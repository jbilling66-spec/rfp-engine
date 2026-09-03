"""P1-23 (P26b-1, B112): the buyer-docx parser's warnings — every table
row or table it dropped is recorded by table index, row and kind, never
by text. Twin expectations are hand-derived from
`tests/fixtures/docx_twins.py`; the synthetic cases build one shape each.
"""

from pathlib import Path

from docx import Document

from engine.structure import parse_buyer_docx
from tests.fixtures.docx_twins import _table

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_qform_twin_records_its_pre_filled_example_row():
    # Hand-derived: table 0's fourth body row carries the buyer's EXAMPLE
    # answer; tables 1 and 2 are fully open.
    parsed = parse_buyer_docx(FIXTURES / "qform-twin.docx")
    assert parsed.warnings == [
        "table 0 row 4: pre-filled row skipped (the buyer's example)"
    ]
    assert parsed.slot_count == 9  # additive — nothing moved


def test_narrative_twin_records_its_filled_reference_table():
    # Hand-derived: the phase/quarter table under the un-numbered
    # "Background" heading is fully filled buyer content (table 0); the
    # resource table (table 1) is a fill-in ask and yields a slot.
    parsed = parse_buyer_docx(FIXTURES / "narrative-twin.docx")
    assert parsed.warnings == [
        "table 0: filled table skipped (buyer content, not an ask)"
    ]


def _doc(rows, *, heading="1. Section"):
    doc = Document()
    doc.add_heading(heading, level=1)
    _table(doc, [["Question", "Response"],
                 ["Describe your approach.", ""]])  # one real ask, so the parse is loud-free
    _table(doc, rows)
    return doc


def _parse(tmp_path, rows):
    path = tmp_path / "case.docx"
    _doc(rows).save(path)
    return parse_buyer_docx(path)


def test_row_without_a_question_is_recorded(tmp_path):
    parsed = _parse(tmp_path, [["Question", "Response"],
                               ["", ""],
                               ["Describe your team.", ""]])
    assert "table 1 row 1: row without a question skipped" in parsed.warnings


def test_incomplete_header_is_recorded(tmp_path):
    parsed = _parse(tmp_path, [["Role", ""], ["PM", ""]])
    assert "table 1: table with an incomplete header row skipped" in parsed.warnings


def test_single_row_table_is_recorded(tmp_path):
    parsed = _parse(tmp_path, [["Role", "Name"]])
    assert "table 1: table with fewer than two rows skipped" in parsed.warnings


def test_partially_answered_table_is_recorded(tmp_path):
    parsed = _parse(tmp_path, [["Role", "Name"], ["PM", "Given"], ["Architect", ""]])
    assert ("table 1: partially answered table skipped (not a clean fill-in "
            "ask)") in parsed.warnings


def test_warnings_never_carry_table_text(tmp_path):
    parsed = _parse(tmp_path, [["Question", "Response"],
                               ["Describe your security posture.",
                                "EXAMPLE ONLY — CONFIDENTIAL"]])
    assert any(line.startswith("table 1 row 1: ") for line in parsed.warnings)
    assert all("CONFIDENTIAL" not in line and "security" not in line
               for line in parsed.warnings)
