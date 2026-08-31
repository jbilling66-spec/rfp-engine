"""The headless waiver lane (B34(15)): waivable+logged (Q2), idempotent,
packaging recounted never hand-edited, boilerplate reasons surfaced as
the registered alert condition."""

import pytest

from engine.runlog import RunLogger, read_run
from engine.validation import VALIDATION_NAME, approve_waiver
from tests.validation.fixtures.validations import (
    AT,
    make_validation_script,
    run_validation_package,
)


@pytest.fixture(scope="module")
def blocked_chain(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("waiver")
    pursuit, report, log = run_validation_package(
        tmp, script=make_validation_script(plant_unsupported=True))
    assert report.blocked and report.tier1_blocks == 1
    blocked = [c for s in pursuit.read_artifact(VALIDATION_NAME)["sections"]
               for c in s.get("claims", []) if c["disposition"] == "block"]
    return pursuit, log, blocked[0]["claim_id"]


def _waiver_records(log):
    return [r for r in read_run(log.path)
            if r.get("record_type") == "validation"
            and r["validation"].get("result") == "waived"]


def test_waiver_unblocks_and_logs(blocked_chain):
    pursuit, log, claim_id = blocked_chain
    result = approve_waiver(
        pursuit, log, claim_id=claim_id, actor="owner",
        reason="Verified offline with the practice lead; count is current.",
        at=AT)
    assert result.status == "waived" and result.warnings == []
    annotated = pursuit.read_artifact(VALIDATION_NAME)
    assert annotated["packaging"] == {"blocked": False, "tier1_blocks": 0,
                                      "waived": 1}
    claim = next(c for s in annotated["sections"]
                 for c in s.get("claims", []) if c["claim_id"] == claim_id)
    assert claim["status"] == "waived" and claim["waived_by"] == "owner"
    assert "waived over unsupported by owner" in claim["reasons"][0]
    records = _waiver_records(log)
    assert len(records) == 1
    assert records[0]["validation"]["waived_by"] == "owner"
    assert "practice lead" in records[0]["validation"]["waiver_reason"]


def test_waiver_is_idempotent_convergent(blocked_chain):
    pursuit, log, claim_id = blocked_chain
    again = approve_waiver(pursuit, log, claim_id=claim_id, actor="owner",
                           reason="second attempt at the same waiver", at=AT)
    assert again.status == "already_waived"
    assert len(_waiver_records(log)) == 1  # no second record, no drift


def test_unknown_and_nonblocking_claims_refused(blocked_chain):
    pursuit, log, _ = blocked_chain
    ghost = approve_waiver(pursuit, log, claim_id="c_ghost_99", actor="owner",
                           reason="a perfectly reasonable justification", at=AT)
    assert ghost.status == "refused"
    passing = next(c["claim_id"]
                   for s in pursuit.read_artifact(VALIDATION_NAME)["sections"]
                   for c in s.get("claims", [])
                   if c["disposition"] == "pass")
    not_blocked = approve_waiver(pursuit, log, claim_id=passing, actor="owner",
                                 reason="a perfectly reasonable justification",
                                 at=AT)
    assert not_blocked.status == "refused"
    assert any("only blocking claims" in w for w in not_blocked.warnings)


def test_boilerplate_reason_surfaces_the_alert(tmp_path):
    pursuit, report, log = run_validation_package(
        tmp_path, script=make_validation_script(plant_unsupported=True))
    claim_id = next(c["claim_id"]
                    for s in pursuit.read_artifact(VALIDATION_NAME)["sections"]
                    for c in s.get("claims", [])
                    if c["disposition"] == "block")
    result = approve_waiver(pursuit, log, claim_id=claim_id, actor="owner",
                            reason="ok", at=AT)
    assert result.status == "waived"  # the human owns the call...
    assert any("boilerplate" in w for w in result.warnings)  # ...the record owns the smell
