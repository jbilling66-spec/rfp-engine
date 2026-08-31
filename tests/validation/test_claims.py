"""Claim extraction: the fact catalog + every code gate on the wire
(B34(5)). Non-vacuity: every drop path is planted once and its warning
asserted; the committed store's 36-fact catalog is read for real."""

from pathlib import Path

from engine.kb import KBStore
from engine.validation import (
    build_extraction_prompt,
    claim_digest,
    fact_catalog,
    parse_extraction_wire,
)

REPO_KB = Path(__file__).resolve().parents[2] / "kb"

PROSE = ("We hold a current SOC 2 Type II attestation for hosted "
         "operations. Our team includes 14 certified ERP consultants.")


def test_fact_catalog_reads_the_committed_fact_sheet():
    facts = fact_catalog(KBStore(REPO_KB))
    assert len(facts) == 36
    assert all(c["layer"] == "fact_sheet" for c in facts)
    assert all(c.get("owner") and c.get("verified_date") for c in facts)
    lapsed = [c for c in facts if c["kb_id"] == "kb_fact000036"]
    assert lapsed and lapsed[0]["review_due"] == "2025-11-01"  # D6 ground truth


def test_extraction_prompt_carries_task_prose_and_catalog():
    facts = [{"kb_id": "kb_fact000001", "title": "SOC 2", "summary": "S."}]
    prompt = build_extraction_prompt(section_title="6. Support",
                                     labeled_prose="SLOT sl_1: text here",
                                     facts=facts)
    assert prompt.startswith("Task: extract claims.")
    assert "SLOT sl_1: text here" in prompt
    assert "FACT kb_fact000001: SOC 2 — S." in prompt


def _wire(rows):
    import json
    return json.dumps({"claims": rows})


def test_good_rows_land_with_code_assigned_ids():
    claims, warnings = parse_extraction_wire(
        _wire([{"slot_id": "sl_1",
                "text": "We hold a current SOC 2 Type II attestation for hosted operations.",
                "tier": 1, "fact_sheet_ref": "kb_ok"},
               {"slot_id": "sl_1",
                "text": "Our team includes 14 certified ERP consultants.",
                "tier": 1, "fact_sheet_ref": None}]),
        section_id="s6", prose_by_slot={"sl_1": PROSE},
        catalog_ids=frozenset({"kb_ok"}))
    assert warnings == []
    assert [c["claim_id"] for c in claims] == ["c_s6_01", "c_s6_02"]
    assert claims[0]["fact_sheet_ref"] == "kb_ok"
    assert claims[1]["fact_sheet_ref"] is None
    assert claims[0]["text_digest"] == claim_digest(claims[0]["text"])


def test_containment_is_whitespace_normalized():
    claims, warnings = parse_extraction_wire(
        _wire([{"slot_id": "sl_1",
                "text": "We hold a current  SOC 2   Type II attestation for hosted operations.",
                "tier": 1, "fact_sheet_ref": None}]),
        section_id="s6", prose_by_slot={"sl_1": PROSE},
        catalog_ids=frozenset())
    assert len(claims) == 1 and warnings == []


def test_hallucinated_claim_dropped_and_reported():
    claims, warnings = parse_extraction_wire(
        _wire([{"slot_id": "sl_1", "text": "We guarantee 99.999% uptime.",
                "tier": 1, "fact_sheet_ref": None}]),
        section_id="s6", prose_by_slot={"sl_1": PROSE},
        catalog_ids=frozenset())
    assert claims == []
    assert any("not present in delivered prose" in w for w in warnings)


def test_unknown_slot_and_bad_tier_dropped_and_reported():
    claims, warnings = parse_extraction_wire(
        _wire([{"slot_id": "sl_ghost", "text": PROSE[:20], "tier": 1},
               {"slot_id": "sl_1",
                "text": "Our team includes 14 certified ERP consultants.",
                "tier": 9}]),
        section_id="s6", prose_by_slot={"sl_1": PROSE},
        catalog_ids=frozenset())
    assert claims == []
    assert any("unknown slot" in w for w in warnings)
    assert any("invalid tier" in w for w in warnings)


def test_invented_ref_becomes_no_referent_with_warning():
    claims, warnings = parse_extraction_wire(
        _wire([{"slot_id": "sl_1",
                "text": "Our team includes 14 certified ERP consultants.",
                "tier": 1, "fact_sheet_ref": "kb_invented"}]),
        section_id="s6", prose_by_slot={"sl_1": PROSE},
        catalog_ids=frozenset({"kb_real"}))
    assert claims[0]["fact_sheet_ref"] is None  # blocks downstream, honestly
    assert any("not in the catalog" in w for w in warnings)


def test_null_slot_matches_section_prose():
    claims, warnings = parse_extraction_wire(
        _wire([{"slot_id": None,
                "text": "Our team includes 14 certified ERP consultants.",
                "tier": 2, "fact_sheet_ref": None}]),
        section_id="s6", prose_by_slot={None: PROSE},
        catalog_ids=frozenset())
    assert len(claims) == 1 and claims[0]["slot_id"] is None


def test_unparseable_wire_reports_and_returns_nothing():
    claims, warnings = parse_extraction_wire(
        "not json at all", section_id="s6",
        prose_by_slot={"sl_1": PROSE}, catalog_ids=frozenset())
    assert claims == []
    assert any("unparseable" in w for w in warnings)


def test_scalar_json_wire_is_unextracted_not_a_crash():
    # The live model submitted literal `null` (P8 live run,
    # poison_att_001) — valid JSON that decodes but cannot be
    # subscripted. Must land in the unparseable lane, never raise.
    claims, warnings = parse_extraction_wire(
        "null", section_id="s6",
        prose_by_slot={"sl_1": PROSE}, catalog_ids=frozenset())
    assert claims == []
    assert any("unparseable" in w for w in warnings)
