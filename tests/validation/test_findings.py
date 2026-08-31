"""The findings contract + the only-claim_audit-blocks choke point
(B34(4,12)). The block-guard fixture here is the D4 requirement: every
declared blocking rule needs a fixture that makes its guard FIRE — v1
shipped a dead blocking branch for weeks because none did."""

import pytest

from engine.contracts import ContractError
from engine.runlog import RunLogger, read_run
from engine.validation import (
    RULE_OWNERS,
    dedupe,
    emit_validation,
    make_finding,
)

CHECKS = {"claim_audit", "coverage", "consistency", "red_team", "voice_polish"}


@pytest.fixture
def log(tmp_path):
    return RunLogger(tmp_path / "pur_v", run_id="run_0001", pursuit_id="pur_v")


def test_rule_owners_is_a_bijection_over_the_five_checks():
    assert set(RULE_OWNERS.values()) == CHECKS  # every check owns >= 1 rule
    # dict keys are unique by construction — the property worth asserting is
    # that every owner is a real check and every check appears.
    for rule, owner in RULE_OWNERS.items():
        assert owner in CHECKS, f"{rule} owned by unknown check {owner}"


def test_finding_id_is_deterministic_and_slot_scoped():
    section = make_finding(check="coverage", rule="length_exceeded",
                           disposition="review", message="too long",
                           section_id="s1")
    slot = make_finding(check="coverage", rule="length_exceeded",
                        disposition="review", message="too long",
                        section_id="s1", slot_id="sl_0002")
    assert section.finding_id == "coverage:length_exceeded:s1"
    assert slot.finding_id == "coverage:length_exceeded:s1:sl_0002"
    assert slot.as_dict()["slot_id"] == "sl_0002"


def test_make_finding_rejects_unowned_and_misowned_rules():
    with pytest.raises(ContractError, match="not in RULE_OWNERS"):
        make_finding(check="coverage", rule="invented_rule",
                     disposition="review", message="m", section_id="s1")
    with pytest.raises(ContractError, match="one rule, one owning check"):
        make_finding(check="consistency", rule="length_exceeded",
                     disposition="review", message="m", section_id="s1")


def test_only_claim_audit_may_raise_a_blocking_finding():
    with pytest.raises(ContractError, match="only 'claim_audit' blocks"):
        make_finding(check="coverage", rule="length_exceeded",
                     disposition="block", message="m", section_id="s1")
    blocking = make_finding(check="claim_audit", rule="tier1_unsupported",
                            disposition="block", message="m", section_id="s1")
    assert blocking.disposition == "block"


def test_dedupe_first_wins():
    first = make_finding(check="coverage", rule="flag_missing",
                         disposition="review", message="first",
                         section_id="s1", slot_id="a")
    dup = make_finding(check="coverage", rule="flag_missing",
                       disposition="review", message="second",
                       section_id="s1", slot_id="a")
    other = make_finding(check="coverage", rule="flag_missing",
                         disposition="review", message="other",
                         section_id="s1", slot_id="b")
    assert dedupe([first, dup, other]) == [first, other]


def test_emit_validation_writes_a_section_grain_record(log):
    emit_validation(log, check="claim_audit", result="block",
                    target={"section_id": "s1", "section_type": "training"},
                    claim_tier=1, claim_text_digest="abc123",
                    fact_sheet_ref="kb_fact000007",
                    span_id="s1:audit", parent_span="stage:validation")
    rec = read_run(log.path)[0]
    assert rec["record_type"] == "validation"
    assert rec["validation"]["check"] == "claim_audit"
    assert rec["validation"]["claim_tier"] == 1
    assert rec["target"]["section_type"] == "training"
    assert rec["span_id"] == "s1:audit"


def test_emit_validation_block_guard_fires_for_foreign_checks(log):
    # THE D4 fixture: a foreign block must raise BEFORE anything lands —
    # it would also silently corrupt totals.tier1_blocks.
    with pytest.raises(ContractError, match="only 'claim_audit' may block"):
        emit_validation(log, check="coverage", result="block",
                        target={"section_id": "s1"})
    assert not log.path.exists()  # nothing landed — not even the file


def test_claim_audit_block_feeds_the_tier1_counter(log):
    # The counter was wired at P0 with zero writers; claim_audit is its
    # first honest writer — and the ONLY check that can reach it (D4).
    emit_validation(log, check="claim_audit", result="block",
                    target={"section_id": "s1"}, claim_tier=1)
    emit_validation(log, check="coverage", result="flag",
                    target={"section_id": "s1"})
    log.run_end(status="completed")
    end = read_run(log.path)[-1]
    assert end["run"]["totals"]["tier1_blocks"] == 1
