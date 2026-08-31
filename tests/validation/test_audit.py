"""The starved verify prompt, the verdict enum gate, the disposition map,
and the staleness clock (B34(1,2,6)). The lapsed-card path runs against
the committed store's deliberately lapsed fact — real ground truth, not a
synthetic construct."""

from pathlib import Path

from engine.kb import KBStore
from engine.validation import (
    audit_claim,
    build_verify_prompt,
    is_stale,
    parse_verdict_wire,
    rule_for_status,
)

REPO_KB = Path(__file__).resolve().parents[2] / "kb"

AT = "2026-08-07T12:00:00"

FRESH_CARD = {"kb_id": "kb_fact000001", "owner": "Compliance Lead",
              "verified_date": "2026-06-15", "review_due": "2026-11-30"}

CLAIM = {"claim_id": "c_s1_01", "slot_id": "sl_1", "text": "t",
         "text_digest": "d", "tier": 1, "fact_sheet_ref": "kb_fact000001"}


def test_verify_prompt_is_starved_one_claim_one_card():
    prompt = build_verify_prompt("We hold X.", FRESH_CARD, "The firm holds X.")
    assert prompt.startswith("Task: verify.")
    assert "CLAIM: We hold X." in prompt
    assert "kb_fact000001" in prompt and "Compliance Lead" in prompt
    # Starvation is structural: the builder ACCEPTS nothing else — no brief,
    # no themes, no surrounding prose parameter exists to leak motive.
    import inspect
    assert list(inspect.signature(build_verify_prompt).parameters) == [
        "claim_text", "fact_card", "fact_body"]


def test_verdict_parse_accepts_the_enum_and_nothing_else():
    assert parse_verdict_wire('{"verdict": "SUPPORTED", "reasons": ["ok"]}') \
        == ("SUPPORTED", ["ok"])
    assert parse_verdict_wire('{"verdict": "MOSTLY_TRUE", "reasons": []}') \
        == (None, [])
    assert parse_verdict_wire("garbage") == (None, [])


def test_tier_2_and_3_are_recorded_never_verified():
    for tier in (2, 3):
        out = audit_claim({**CLAIM, "tier": tier}, verdict=None, reasons=[],
                          fact_card=None, at=AT)
        assert (out["status"], out["disposition"]) == ("not_audited", "pass")


def test_no_referent_blocks_as_unverifiable():
    out = audit_claim({**CLAIM, "fact_sheet_ref": None}, verdict=None,
                      reasons=[], fact_card=None, at=AT)
    assert (out["status"], out["disposition"]) == ("unverifiable", "block")
    assert rule_for_status(out["status"]) == "tier1_unverifiable"


def test_unparseable_verdict_is_never_an_approval():
    out = audit_claim(CLAIM, verdict=None, reasons=[], fact_card=FRESH_CARD,
                      at=AT)
    assert (out["status"], out["disposition"]) == ("unverifiable", "block")


def test_scalar_and_unhashable_verdict_wires_degrade_to_none():
    # Valid-JSON scalars (`null` — seen from the live model, P8) have no
    # .get; an object-valued verdict is unhashable against the enum set.
    # Both are non-verdicts, and a non-verdict is never an approval.
    assert parse_verdict_wire("null") == (None, [])
    assert parse_verdict_wire('{"verdict": {"v": 1}, "reasons": []}') \
        == (None, [])


def test_supported_fresh_passes_with_reasons():
    out = audit_claim(CLAIM, verdict="SUPPORTED", reasons=["quoted words"],
                      fact_card=FRESH_CARD, at=AT)
    assert (out["status"], out["disposition"]) == ("supported", "pass")
    assert out["reasons"] == ["quoted words"]


def test_supported_on_the_committed_lapsed_card_flags_stale():
    lapsed = next(c for c in KBStore(REPO_KB).list_cards()
                  if c["kb_id"] == "kb_fact000036")
    assert is_stale(lapsed, AT)  # the D6 ground truth really is lapsed
    out = audit_claim({**CLAIM, "fact_sheet_ref": "kb_fact000036"},
                      verdict="SUPPORTED", reasons=["ok"], fact_card=lapsed,
                      at=AT)
    assert (out["status"], out["disposition"]) == ("stale", "flag")
    assert "review_due" in out["reasons"][0]
    assert rule_for_status("stale") == "tier1_stale"


def test_stale_boundary_is_strictly_before_the_clock():
    card = {**FRESH_CARD, "review_due": "2026-08-07"}
    assert not is_stale(card, AT)  # due today = not yet lapsed
    assert is_stale({**FRESH_CARD, "review_due": "2026-08-06"}, AT)


def test_every_failing_verdict_blocks():
    for verdict, status in (("OVERSTATED", "overstated"),
                            ("UNSUPPORTED", "unsupported"),
                            ("MISATTRIBUTED", "misattributed")):
        out = audit_claim(CLAIM, verdict=verdict, reasons=["r"],
                          fact_card=FRESH_CARD, at=AT)
        assert (out["status"], out["disposition"]) == (status, "block")
        assert rule_for_status(status).startswith("tier1_")
