"""schemas/template-fill-facts.schema.json after P26a item 1 (P1-27): the
record now says which copy was written and why the buyer copy was
withheld — filled_by_hand and fields_written per row, remaining_by_hand,
scaffolding_removed, working_copy, buyer_copy_produced at the top."""

import pytest

from engine.contracts import ContractError, validate

BASE = {
    "pursuit_id": "pur_facts", "plan_sha256": "a" * 64,
    "draft_sha256": "b" * 64, "revision_n": 0, "confirmed_by": "Pat",
    "at": "2026-09-02T10:00:00Z",
    "template_file": "config/templates/firm-default-template.docx",
    "template_sha256": "c" * 64,
    "output_file": "exports/submission/response.docx",
    "sections": [], "remaining_guidance": [],
}


def test_the_p1_27_fields_validate_together():
    validate("template_fill_facts", {
        **BASE,
        "working_copy": "exports/review/response-working.docx",
        "buyer_copy_produced": False,
        "scaffolding_removed": ["Firm Response Template",
                                "How to Use This Template"],
        "remaining_by_hand": ["Pricing & Commercial Terms: missing fee"],
        "sections": [
            {"section_id": "", "slot_id": "s-front-meta",
             "docx_anchor": "Front matter", "decision": "filled_by_hand",
             "reason": "every field supplied",
             "fields_written": ["rfp_title", "submitted_by"]},
            {"section_id": "", "slot_id": "s-h11",
             "docx_anchor": "11.  Pricing", "decision": "fill_by_hand",
             "reason": "missing fee", "fields_written": []},
        ],
    })


def test_pre_p26a_records_still_validate():
    validate("template_fill_facts", BASE)


@pytest.mark.parametrize("bad", [
    {"sections": [{"section_id": "", "docx_anchor": "x",
                   "decision": "filled_by_robot", "reason": "r"}]},
    {"buyer_copy_produced": "yes"},
    {"remaining_by_hand": "Pricing"},
    {"extra": 1},
])
def test_the_record_stays_closed(bad):
    with pytest.raises(ContractError):
        validate("template_fill_facts", {**BASE, **bad})
