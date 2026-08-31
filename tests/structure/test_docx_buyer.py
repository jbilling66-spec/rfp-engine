"""Buyer-DOCX parser acceptance (P16/C3): outline-twin and qform-twin
parse to client_provided TargetSlots.

Goldens hand-derived from the twins' construction. outline-twin: five
numbered H2 sections + one H3 child, all instruction-carrying, so six
answerable slots (section 2 stays answerable WITH a child — a buyer
that puts demands on a parent section gets a slot for it). qform-twin:
three numbered forms (headers) + five open question rows (the EXAMPLE
pre-filled row is NOT an ask) + one references grid = 3 + 5 + 1.
"""

from pathlib import Path

import pytest

from engine.contracts import validate
from engine.structure import StructureError
from engine.structure.docx_buyer import WORDS_PER_PAGE, parse_buyer_docx

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture(scope="module")
def outline():
    return parse_buyer_docx(FIXTURES / "outline-twin.docx")


@pytest.fixture(scope="module")
def qform():
    return parse_buyer_docx(FIXTURES / "qform-twin.docx")


def test_every_slot_validates(outline, qform):
    for parsed in (outline, qform):
        assert parsed.source_mode == "client_provided"
        for slot in parsed.slots:
            validate("target_slot", slot)


def test_outline_sections_are_answerable_slots_with_refs(outline):
    assert outline.slot_count == 6
    by_ref = {s["ref_id"]: s for s in outline.slots}
    assert list(by_ref) == ["1", "2", "2.1", "3", "4", "5"]
    assert all(not s.get("is_header") for s in outline.slots)
    assert by_ref["1"]["response_shape"] == "prose"
    assert by_ref["1"]["question_text"].startswith("Provide a brief narrative")
    # verbatim anchor for round-trip; buyer numbering preserved on ref_id
    assert by_ref["2.1"]["source_locator"]["docx_anchor"] == (
        "2.1 Project Timeline")
    assert by_ref["2.1"]["parent"] == by_ref["2"]["slot_id"]


def test_outline_page_limit_becomes_words_and_verbatim(outline):
    limited = next(s for s in outline.slots if s["ref_id"] == "1")
    assert limited["constraints"]["max_words"] == 2 * WORDS_PER_PAGE
    assert limited["constraints"]["format"] == (
        "shall not exceed two (2) pages")
    unlimited = next(s for s in outline.slots if s["ref_id"] == "3")
    assert "constraints" not in unlimited


def test_outline_stated_weight_and_optional_section(outline):
    weighted = next(s for s in outline.slots if s["ref_id"] == "2")
    assert weighted["eval_weight"] == 30
    optional = next(s for s in outline.slots if s["ref_id"] == "5")
    assert optional["required"] is False
    # the default stays OMITTED, never written (writers-omit)
    assert all("required" not in s for s in outline.slots
               if s["ref_id"] != "5")
    assert all("eval_weight" not in s for s in outline.slots
               if s["ref_id"] != "2")


def test_qform_open_rows_slot_and_example_row_does_not(qform):
    assert qform.slot_count == 9  # 3 headers + 5 questions + 1 grid
    headers = [s for s in qform.slots if s.get("is_header")]
    assert [s["ref_id"] for s in headers] == ["1", "2", "3"]
    questions = [s for s in qform.slots
                 if s["slot_id"].startswith("s-t") and "-r" in s["slot_id"]]
    assert len(questions) == 5
    assert not any("EXAMPLE" in (s.get("question_text") or "")
                   or "quality program" in (s.get("question_text") or "")
                   for s in qform.slots)  # the pre-filled row is not an ask


def test_qform_shapes_come_from_the_shared_trigger_vocabulary(qform):
    shape = {s["question_text"]: s["response_shape"]
             for s in qform.slots if not s.get("is_header")
             and s.get("question_text")}
    assert shape["Do you subcontract any implementation services?"] == (
        "boolean")
    assert shape["How many ERP implementations have you completed in the "
                 "last five (5) years?"] == "numeric"
    assert shape["Describe your project governance model."] == "prose"


def test_qform_answer_cells_rederive_for_writeback(qform):
    """The frozen slot schema carries no table addresses — write-back
    re-derives them from the digest-bound source (server-side truth,
    never a client echo). Every question slot must resolve to a cell;
    the pre-filled EXAMPLE row must resolve to none."""
    from engine.structure.docx_buyer import question_cell_map

    cells = question_cell_map(FIXTURES / "qform-twin.docx")
    questions = [s for s in qform.slots
                 if s["slot_id"].startswith("s-t") and "-r" in s["slot_id"]]
    assert {s["slot_id"] for s in questions} == set(cells)
    governance = next(s for s in qform.slots
                      if s.get("question_text") == (
                          "Describe your project governance model."))
    assert cells[governance["slot_id"]]["row"] == 1
    assert cells[governance["slot_id"]]["column"] == 1
    assert governance["source_locator"]["file"] == "qform-twin.docx"
    assert governance["parent"] == "s-r2"


def test_qform_references_grid_is_one_template_fill_slot(qform):
    grid = next(s for s in qform.slots
                if s.get("fill_type") == "template_fill")
    assert grid["response_shape"] == "table"
    assert [f["key"] for f in grid["response_fields"]] == [
        "reference", "contact", "phone"]
    assert grid["parent"] == "s-r3"


def test_unrecognizable_docx_refuses_loudly(tmp_path):
    from docx import Document
    doc = Document()
    doc.add_paragraph("A letter with no numbered sections or forms.")
    plain = tmp_path / "letter.docx"
    doc.save(plain)
    with pytest.raises(StructureError, match="never free_flow"):
        parse_buyer_docx(plain)
    with pytest.raises(StructureError, match="no document"):
        parse_buyer_docx(tmp_path / "absent.docx")
