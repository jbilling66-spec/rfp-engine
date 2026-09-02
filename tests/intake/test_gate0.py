"""Gate 0 (P15/B70): the human confirms the engine's READING of the
package before research spends. Mirrors Gate 1's contract discipline —
validation before write, idempotent-convergent, raise-never-drop — with
the intake deltas: checkpoint-keyed (no status value), corrections
address the assumption register by field path, answers/skips address the
persisted gaps, rejection is the redo door, and open questions never
block a decision (the questioner is advisory, E5/A4)."""

import json

import pytest

from engine.contracts import request_digest
from engine.contracts import ContractError, validate
from engine.intake.gate import approve_gate0
from engine.llm import effective_config
from engine.runlog import RunLogger, read_run
from engine.version import engine_version
from tests.intake.fixtures.packages import RAMBLE, _wire_from_prompt, run_package

GATE_AT = "2026-08-28T09:00:00Z"


def _gate_log(pursuit):
    log = RunLogger(pursuit.root, pursuit.new_run_id(), pursuit.pursuit_id)
    log.run_start(mode="dry_run", engine_version=engine_version(),
                  config=effective_config(), kb_snapshot="kb@empty")
    return log


def _starving(prompt: str) -> str:
    wire = json.loads(_wire_from_prompt(prompt))
    wire["procurement"].pop("what_is_bought", None)
    return json.dumps(wire)


@pytest.fixture()
def gapped(tmp_path):
    pursuit, _ = run_package(tmp_path, "pdf",
                             script={"intake_analyst": _starving})
    return pursuit


@pytest.fixture()
def clean(tmp_path):
    pursuit, _ = run_package(tmp_path, "pdf", ramble=RAMBLE)
    return pursuit


def test_approval_stamps_confirms_and_checkpoints(clean):
    log = _gate_log(clean)
    result = approve_gate0(clean, log, decision="approved",
                           actor="Pat Lead", at=GATE_AT, notes="read it")
    log.run_end(status="completed")
    brief = clean.read_artifact("brief.json")
    validate("bid_brief", brief)
    assert brief["gate0"] == {
        "approved_by": "Pat Lead", "at": GATE_AT, "notes": "read it",
        "request_sha256": request_digest(decision="approved",
                                         notes="read it")}
    # blanket confirmation is the human act the register exists for
    assert all(e["status"] == "confirmed"
               for e in brief["intake"]["assumptions"])
    assert "gate_0" in clean.completed_stages()
    assert clean.checkpoint_payload("gate_0")["decision"] == "approved"
    records = read_run(clean.root / "runs" / result.brief_path.parent.name
                       if False else
                       clean.root / "runs" / "run_0002" / "run.jsonl")
    gates = [r["gate"] for r in records if r["record_type"] == "gate"]
    assert gates == [{"which": "gate_0_intake", "decision": "approved",
                      "actor": "Pat Lead", "auto_approved": False,
                      "wait_ms": 0, "notes": "read it"}]  # P1-15
    # Gate 1's fields stay Gate 1's: no created stamp, status untouched
    assert "created" not in brief
    assert brief["status"] == "draft"


def test_auto_approval_leaves_the_register_unconfirmed(clean):
    log = _gate_log(clean)
    approve_gate0(clean, log, decision="auto_approved", actor="ci",
                  at=GATE_AT, auto_approved=True)
    log.run_end(status="completed")
    brief = clean.read_artifact("brief.json")
    assert all(e["status"] == "unconfirmed"
               for e in brief["intake"]["assumptions"])
    assert "gate_0" in clean.completed_stages()


def test_correction_rewrites_the_field_and_stamps_the_register(clean):
    log = _gate_log(clean)
    approve_gate0(clean, log, decision="approved_with_edits",
                  actor="Pat Lead", at=GATE_AT, corrections=[
                      {"field": "procurement.what_is_bought",
                       "value": "managed payroll transformation"}])
    log.run_end(status="completed")
    brief = clean.read_artifact("brief.json")
    validate("bid_brief", brief)
    assert brief["procurement"]["what_is_bought"] == \
        "managed payroll transformation"
    entry = next(e for e in brief["intake"]["assumptions"]
                 if e["field"] == "procurement.what_is_bought")
    assert entry["status"] == "corrected"
    assert entry["corrected_to"] == "managed payroll transformation"
    assert entry["corrected_by"] == "Pat Lead"
    # everything untouched was still human-confirmed by the approval
    others = [e for e in brief["intake"]["assumptions"] if e is not entry]
    assert others and all(e["status"] == "confirmed" for e in others)


def test_weight_text_correction_reparses_the_number(clean):
    brief = clean.read_artifact("brief.json")
    idx, row = next(
        (i, r) for i, r in enumerate(brief["requirements_matrix"])
        if "weight_text" in r and "weight" in r)
    field = f"requirements_matrix[{idx}].weight_text"
    log = _gate_log(clean)
    approve_gate0(clean, log, decision="approved_with_edits",
                  actor="Pat Lead", at=GATE_AT,
                  corrections=[{"field": field, "value": "Capability (55%)"}])
    log.run_end(status="completed")
    after = clean.read_artifact("brief.json")["requirements_matrix"][idx]
    assert after["weight_text"] == "Capability (55%)"
    assert after["weight"] == 55.0  # the code parse followed the correction


def test_code_parsed_entries_refuse_direct_correction(clean):
    brief = clean.read_artifact("brief.json")
    code_field = next(e["field"] for e in brief["intake"]["assumptions"]
                      if e["source"] == "code")
    log = _gate_log(clean)
    with pytest.raises(ContractError, match="code-parsed"):
        approve_gate0(clean, log, decision="approved_with_edits",
                      actor="Pat Lead", at=GATE_AT,
                      corrections=[{"field": code_field, "value": 99}])
    log.run_end(status="failed")


def test_unknown_field_and_unknown_gap_raise_never_drop(clean):
    log = _gate_log(clean)
    with pytest.raises(ContractError, match="not on the assumption"):
        approve_gate0(clean, log, decision="approved_with_edits",
                      actor="Pat Lead", at=GATE_AT,
                      corrections=[{"field": "buyer.mood", "value": "x"}])
    with pytest.raises(ContractError, match="unknown intake gap"):
        approve_gate0(clean, log, decision="approved_with_edits",
                      actor="Pat Lead", at=GATE_AT,
                      answers=[{"gap_id": "gap_nope_01", "answer": "hi"}])
    log.run_end(status="failed")


def test_answers_and_skips_flip_gaps_and_reach_the_log(gapped):
    brief = gapped.read_artifact("brief.json")
    gap_ids = [g["gap_id"] for g in brief["intake"]["gaps"]]
    assert gap_ids
    log = _gate_log(gapped)
    approve_gate0(gapped, log, decision="approved_with_edits",
                  actor="Pat Lead", at=GATE_AT,
                  answers=[{"gap_id": gap_ids[0],
                            "answer": "ERP implementation services"}],
                  skips=gap_ids[1:])
    log.run_end(status="completed")
    brief = gapped.read_artifact("brief.json")
    validate("bid_brief", brief)
    by_id = {g["gap_id"]: g for g in brief["intake"]["gaps"]}
    assert by_id[gap_ids[0]]["status"] == "answered"
    assert by_id[gap_ids[0]]["answered_by"] == "Pat Lead"
    for gid in gap_ids[1:]:
        assert by_id[gid]["status"] == "skipped"
    records = read_run(gapped.root / "runs" / "run_0002" / "run.jsonl")
    resolutions = [r["gap"]["resolution"] for r in records
                   if r["record_type"] == "gap"]
    assert "answered" in resolutions
    assert resolutions.count("descoped") == len(gap_ids) - 1


def test_open_questions_never_block_the_decision(gapped):
    """The advisory contract at gate level (E5/A4): every gap left OPEN
    and the gate still decides — no gate consumes the question list."""
    log = _gate_log(gapped)
    result = approve_gate0(gapped, log, decision="approved",
                           actor="Pat Lead", at=GATE_AT)
    log.run_end(status="completed")
    assert result.decision == "approved"
    brief = gapped.read_artifact("brief.json")
    assert all(g["status"] == "open" for g in brief["intake"]["gaps"])
    assert "gate_0" in gapped.completed_stages()


def test_rejection_is_the_redo_door(gapped):
    log = _gate_log(gapped)
    with pytest.raises(ContractError, match="notes are required"):
        approve_gate0(gapped, log, decision="rejected",
                      actor="Pat Lead", at=GATE_AT)
    result = approve_gate0(gapped, log, decision="rejected",
                           actor="Pat Lead", at=GATE_AT,
                           notes="wrong attachment set — re-upload")
    log.run_end(status="completed")
    assert result.decision == "rejected"
    brief = gapped.read_artifact("brief.json")
    assert "gate0" not in brief  # nothing stamped
    for cleared in ("intake", "bid_brief", "gate_0"):
        assert cleared not in gapped.completed_stages()


def test_idempotent_convergent_and_conflicting(clean):
    log = _gate_log(clean)
    first = approve_gate0(clean, log, decision="approved",
                          actor="Pat Lead", at=GATE_AT)
    again = approve_gate0(clean, log, decision="approved",
                          actor="Pat Lead", at=GATE_AT)
    assert again.converged and again.brief_sha256 == first.brief_sha256
    with pytest.raises(ContractError, match="already decided"):
        approve_gate0(clean, log, decision="approved",
                      actor="Sam Other", at=GATE_AT)
    # P0-5/P2-13: a fresh clock converges; different notes refuse
    fresh = approve_gate0(clean, log, decision="approved", actor="Pat Lead",
                          at="2026-08-28T10:00:00Z")
    assert fresh.converged and fresh.brief_sha256 == first.brief_sha256
    assert clean.checkpoint_payload("gate_0")["at"] == GATE_AT
    with pytest.raises(ContractError, match="already decided"):
        approve_gate0(clean, log, decision="approved", actor="Pat Lead",
                      at=GATE_AT, notes="changed my reading")
    log.run_end(status="completed")


def test_crash_after_stamp_completes_from_the_stamp_with_a_fresh_clock(clean):
    """Gate 0's crash window: brief stamped, checkpoint missing. A
    same-request resubmit with a different clock completes with the
    stamp's clock; a different request refuses."""
    log = _gate_log(clean)
    approve_gate0(clean, log, decision="approved", actor="Pat Lead",
                  at=GATE_AT, notes="read it")
    (clean.root / "checkpoints" / "gate_0.json").unlink()
    with pytest.raises(ContractError, match="different decision"):
        approve_gate0(clean, log, decision="approved", actor="Pat Lead",
                      at="2026-08-28T10:00:00Z", notes="read it twice")
    again = approve_gate0(clean, log, decision="approved", actor="Pat Lead",
                          at="2026-08-28T10:00:00Z", notes="read it")
    assert again.converged is True
    assert clean.checkpoint_payload("gate_0")["at"] == GATE_AT
    assert clean.read_artifact("brief.json")["gate0"]["at"] == GATE_AT
    log.run_end(status="completed")


def test_crash_before_brief_write_replays_no_gap_lines(gapped, monkeypatch):
    """P2-11: gap lines used to be emitted INSIDE the disposition loop,
    before the brief write, so a crash between them replayed every line
    on resume. Now nothing lands before the write; the resume emits each
    line exactly once."""
    gap_ids = [g["gap_id"] for g in
               gapped.read_artifact("brief.json")["intake"]["gaps"]]
    log = _gate_log(gapped)
    args = dict(decision="approved_with_edits", actor="Pat Lead", at=GATE_AT,
                answers=[{"gap_id": gap_ids[0],
                          "answer": "ERP implementation services"}],
                skips=gap_ids[1:])

    class Boom(Exception):
        pass

    def crash(*a, **k):
        raise Boom("crash before the brief write")

    monkeypatch.setattr(gapped, "write_artifact", crash)
    with pytest.raises(Boom):
        approve_gate0(gapped, log, **args)
    monkeypatch.undo()
    assert not [r for r in read_run(log.path) if r["record_type"] == "gap"]
    result = approve_gate0(gapped, log, **args)
    assert result.converged is False
    gaps = [r for r in read_run(log.path) if r["record_type"] == "gap"]
    assert len(gaps) == len(gap_ids)  # one line per action, never doubled
    log.run_end(status="completed")
