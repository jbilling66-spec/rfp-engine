"""The validation stage end-to-end (B34): refusal gates spend nothing,
the happy chain writes a schema-valid annotated draft with real audit
outcomes, planted defects block/flag honestly, and the cancel asymmetry
holds — a killed validation leaves checkpoints but NO artifact, and
resume completes byte-identically to a never-killed chain."""

import json

import pytest

from engine.runlog import RunLogger, read_run
from engine.validation import VALIDATION_NAME, run_validation
from tests.validation.fixtures.validations import (
    AT,
    SOC2_FACT,
    make_validation_script,
    run_validation_package,
    run_validation_run,
)


@pytest.fixture(scope="module")
def happy(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("val-happy")
    pursuit, report, log = run_validation_package(tmp)
    return tmp, pursuit, report, log


def _validation_records(log):
    return [r for r in read_run(log.path)
            if r["record_type"] == "validation"]


def test_happy_chain_completes_with_receipts(happy):
    _, pursuit, report, log = happy
    assert report.status == "complete"
    assert not report.blocked and report.tier1_blocks == 0
    annotated = pursuit.read_artifact(VALIDATION_NAME)
    drafted = [s for s in annotated["sections"]
               if s["draft_status"] == "drafted"]
    assert len(drafted) == 2  # gapcase: delivery + special-requirements
    # The SOC 2 steering sentence audited as a SUPPORTED Tier-1 claim
    # against the committed fact sheet — no hand-wiring anywhere.
    soc2 = [c for s in drafted for c in s.get("claims", [])
            if c.get("fact_sheet_ref") == SOC2_FACT]
    assert soc2 and soc2[0]["status"] == "supported"
    assert soc2[0]["tier"] == 1 and soc2[0]["disposition"] == "pass"


def test_every_check_records_per_drafted_section(happy):
    _, pursuit, report, log = happy
    records = _validation_records(log)
    seen = {(r["validation"]["check"], r["target"]["section_id"])
            for r in records}
    for check in ("claim_audit", "coverage", "consistency", "red_team",
                  "voice_polish"):
        for section in ("1-delivery-approach", "2-special-requirements"):
            assert (check, section) in seen, f"missing {check} for {section}"
    # Red-team scores are recorded honestly (advisory never means silent).
    assert all(r["validation"].get("score") == 8 for r in records
               if r["validation"]["check"] == "red_team")


def test_validated_status_on_live_plan_only(happy):
    _, pursuit, report, log = happy
    live = pursuit.read_artifact("plan.json")
    frozen = pursuit.read_artifact("plan.frozen.json")
    statuses = {s["section_id"]: s.get("draft_status")
                for s in live["sections"]}
    assert statuses["1-delivery-approach"] == "validated"
    assert statuses["2-special-requirements"] == "validated"
    assert all("draft_status" not in s for s in frozen["sections"])


def test_refusal_gates_spend_nothing(tmp_path):
    from engine.kb import KBStore
    from engine.llm import FakeCaller, TracedCaller
    from engine.workspace import PursuitDir

    pursuit = PursuitDir(tmp_path / "pur_bare", "pur_bare")
    log = RunLogger(pursuit.root, "run_0001", "pur_bare")
    caller = TracedCaller(FakeCaller({}), log)
    store = KBStore(tmp_path / "kb")
    report = run_validation(pursuit, caller, log, store, at=AT)
    assert report.status == "refused"
    records = read_run(log.path)
    assert [r["record_type"] for r in records] == ["error"]
    assert records[0]["error"]["code"] == "missing_draft"
    assert not (pursuit.root / VALIDATION_NAME).exists()


def test_plan_sha_mismatch_refuses(tmp_path):
    pursuit, report, log = run_validation_package(tmp_path)
    # Tamper the envelope's binding, then re-run: the chain must refuse.
    envelope = pursuit.read_artifact("drafts/draft.json")
    envelope["plan_sha256"] = "0" * 64
    pursuit.write_artifact("draft", envelope, name="drafts/draft.json")
    _, report2, log2 = run_validation_run(tmp_path, pursuit)
    assert report2.status == "refused"
    errors = [r for r in read_run(log2.path) if r["record_type"] == "error"]
    assert errors[0]["error"]["code"] == "plan_sha_mismatch"


def test_planted_unsupported_blocks(tmp_path):
    pursuit, report, log = run_validation_package(
        tmp_path, script=make_validation_script(plant_unsupported=True))
    assert report.blocked and report.tier1_blocks == 1
    annotated = pursuit.read_artifact(VALIDATION_NAME)
    assert annotated["packaging"] == {"blocked": True, "tier1_blocks": 1,
                                      "waived": 0}
    blocked = [c for s in annotated["sections"]
               for c in s.get("claims", []) if c["disposition"] == "block"]
    assert blocked[0]["status"] == "unsupported"
    findings = [f for s in annotated["sections"]
                for f in s.get("findings", [])]
    assert any(f["rule"] == "tier1_unsupported" and f["disposition"] == "block"
               for f in findings)
    # The counter honesty chain: the trace's totals agree.
    end = read_run(log.path)[-1]
    assert end["run"]["totals"]["tier1_blocks"] == 1


def test_planted_stale_flags_not_blocks(tmp_path):
    pursuit, report, log = run_validation_package(
        tmp_path, script=make_validation_script(plant_stale=True))
    assert not report.blocked
    annotated = pursuit.read_artifact(VALIDATION_NAME)
    stale = [c for s in annotated["sections"] for c in s.get("claims", [])
             if c["status"] == "stale"]
    assert stale and stale[0]["disposition"] == "flag"
    assert "review_due" in stale[0]["reasons"][0]
    audit_records = [r for r in _validation_records(log)
                     if r["validation"]["check"] == "claim_audit"]
    assert any(r["validation"]["result"] == "flag" for r in audit_records)


def test_planted_hallucination_dropped_and_reported(tmp_path):
    pursuit, report, log = run_validation_package(
        tmp_path, script=make_validation_script(plant_hallucinated=True))
    assert any("not present in delivered prose" in w for w in report.warnings)
    annotated = pursuit.read_artifact(VALIDATION_NAME)
    texts = [c["text"] for s in annotated["sections"]
             for c in s.get("claims", [])]
    assert not any("teleportation" in t for t in texts)


def test_planted_contradiction_and_weak_section_flag(tmp_path):
    pursuit, report, log = run_validation_package(
        tmp_path, script=make_validation_script(plant_contradiction=True,
                                                plant_weak=True))
    annotated = pursuit.read_artifact(VALIDATION_NAME)
    findings = [f for s in annotated["sections"]
                for f in s.get("findings", [])]
    assert sum(1 for f in findings if f["rule"] == "contradiction") == 2
    weak = [f for f in findings if f["rule"] == "weak_section"]
    assert weak and weak[0]["disposition"] == "advisory"
    assert not report.blocked  # neither lane can block (Q2)


def test_cancel_asymmetry_and_byte_identical_resume(tmp_path_factory):
    straight_tmp = tmp_path_factory.mktemp("val-straight")
    straight_pursuit, _, _ = run_validation_package(straight_tmp)
    straight_bytes = (straight_pursuit.root / VALIDATION_NAME).read_bytes()

    killed_tmp = tmp_path_factory.mktemp("val-killed")
    from tests.drafting.fixtures.drafts import run_drafting_package
    pursuit, draft_report = run_drafting_package(killed_tmp)
    assert draft_report.status == "complete"
    with pytest.raises(RuntimeError, match="scripted validation death"):
        run_validation_run(
            killed_tmp, pursuit,
            script=make_validation_script(
                fail_on_section="2. Special Requirements"))
    # The asymmetry: checkpoint survived, artifact does NOT exist.
    assert "validation" in pursuit.completed_stages()
    assert not (pursuit.root / VALIDATION_NAME).exists()

    # Resume with a healthy script: completes, and the artifact is
    # byte-identical to the never-killed chain's.
    _, report, resumed_log = run_validation_run(killed_tmp, pursuit)
    assert report.status == "complete"
    assert (pursuit.root / VALIDATION_NAME).read_bytes() == straight_bytes
    # Zero respend on the finished section: the resumed run's audit calls
    # are all for the killed section.
    calls = [r for r in read_run(resumed_log.path)
             if r["record_type"] == "agent_call"
             and r["agent"] == "claim_auditor"]
    assert len(calls) == 1
    assert calls[0]["target"]["section_id"] == "2-special-requirements"
