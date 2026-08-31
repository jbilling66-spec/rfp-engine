"""Firm-template parser acceptance (P16/C2): template-twin.docx parses
to firm_default TargetSlots.

Goldens are hand-derived from the twin's construction (14 numbered
sections, one H2 under §5, one content vehicle per section, the front
metadata table, the §12 inline paragraph): 1 record + 15 headers + 14
content + 1 inline = 31 slots — never transcribed from parser output.
"""

from pathlib import Path

import pytest

from engine.contracts import validate
from engine.structure import (
    DOCX_PARSER_VERSION,
    StructureError,
    parse_default_template,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
TWIN = FIXTURES / "template-twin.docx"


@pytest.fixture(scope="module")
def parsed():
    return parse_default_template(TWIN)


def test_every_slot_validates_and_is_firm_default(parsed):
    assert parsed.slot_count == 31
    assert parsed.source_mode == "firm_default"
    assert parsed.parser_version == DOCX_PARSER_VERSION
    for slot in parsed.slots:
        validate("target_slot", slot)
        assert slot["source_mode"] == "firm_default"


def test_parse_is_deterministic():
    a = parse_default_template(TWIN)
    b = parse_default_template(TWIN)
    assert a.slots == b.slots
    assert a.source_sha256 == b.source_sha256


def test_fourteen_numbered_sections_become_header_slots(parsed):
    headers = [s for s in parsed.slots
               if s.get("is_header") and s["slot_id"].endswith("-hdr")]
    assert len(headers) == 14
    assert headers[0]["source_locator"]["docx_anchor"] == "1.  Cover Letter"
    assert headers[0]["path"] == "Cover Letter"  # cleaned for humans
    assert headers[-1]["source_locator"]["docx_anchor"] == "14.  Appendices"
    assert all(s["response_shape"] == "none" for s in headers)


def test_front_matter_yields_only_the_metadata_record(parsed):
    meta = parsed.slots[0]
    assert meta["slot_id"] == "s-front-meta"
    assert meta["response_shape"] == "record"
    keys = [f["key"] for f in meta["response_fields"]]
    assert keys[0] == "prepared_for_client"
    assert len(keys) == 7
    locator = meta["response_fields"][0]["source_locator"]
    assert locator == {"table_index": 0, "row": 1, "column": 1}
    # "How to Use This Template" produced NOTHING besides the record.
    assert not any("How to Use" in (s.get("question_text") or "")
                   for s in parsed.slots)


def test_guidance_becomes_question_text_and_one_page_constrains(parsed):
    exec_summary = next(s for s in parsed.slots if s["slot_id"] == "s-h02")
    assert exec_summary["question_text"].startswith("▸ WHAT TO INCLUDE")
    assert exec_summary["response_shape"] == "prose"
    assert exec_summary["constraints"] == {
        "brevity": "terse", "flags": ["one_page"]}
    # every OTHER prose section carries no constraints (writers omit)
    plain = next(s for s in parsed.slots if s["slot_id"] == "s-h01")
    assert "constraints" not in plain


def test_case_block_and_pricing_grid_are_table_slots(parsed):
    case = next(s for s in parsed.slots if s["slot_id"] == "s-h10")
    assert case["response_shape"] == "table"
    assert [f["key"] for f in case["response_fields"]] == [
        "client", "scope", "outcome"]
    grid = next(s for s in parsed.slots if s["slot_id"] == "s-h11")
    assert [(f["label"], f["type"]) for f in grid["response_fields"]] == [
        ("Milestone", "text"), ("Fee", "currency"),
        ("Duration (weeks)", "number")]
    assert all("table_index" in f["source_locator"]
               for f in grid["response_fields"])


def test_h2_and_inline_paragraph_slots(parsed):
    h2 = next(s for s in parsed.slots
              if s["slot_id"] == "s-h05-timeline_milestones")
    assert h2["is_header"] is True
    assert h2["parent"] == "s-h05-hdr"
    assert h2["source_locator"]["docx_anchor"].endswith(
        "> Timeline & Milestones")
    inline = next(s for s in parsed.slots if s["slot_id"] == "s-h12-1")
    assert inline["response_shape"] == "prose"
    assert inline["question_text"].startswith("Payment schedule & terms")


def test_missing_or_headerless_template_refuses(tmp_path):
    with pytest.raises(StructureError, match="no template"):
        parse_default_template(tmp_path / "absent.docx")
    from docx import Document
    doc = Document()
    doc.add_heading("1.  Only A Header", level=1)
    empty = tmp_path / "headers-only.docx"
    doc.save(empty)
    with pytest.raises(StructureError, match="headers only"):
        parse_default_template(empty)
