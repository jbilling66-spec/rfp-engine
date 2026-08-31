"""Gate 1 (P5 acceptance, WP4/G5/B5/T7): approval is recorded in the
artifact, approval unlocks the fork (the exact predicate P6 will check),
edits are honored or raise, rejection declines, the frozen copy is
byte-equal, created is stamped only here, and the gate is idempotent."""

import pytest

from engine.contracts import ContractError, validate
from engine.runlog import RunLogger, read_run
from engine.strategy import FROZEN_BRIEF, approve_gate1
from tests.strategy.fixtures.strategies import (
    ACTOR,
    GATE_AT,
    KEEP_INDEXES,
    bare_strategy_run,
    run_strategy_package,
)


@pytest.fixture(scope="module")
def approved(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("gate1")
    return run_strategy_package(tmp, notes="strong angle set")


@pytest.fixture(scope="module")
def pending(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("gate1_pending")
    return run_strategy_package(tmp, gate=None)


def _reopen_log(pursuit):
    return RunLogger(pursuit.root, pursuit.latest_run_id(), pursuit.pursuit_id)


# ---------------------------------------------------------------- approval


def test_approval_recorded_in_brief(approved):
    pursuit, _ = approved
    brief = pursuit.read_artifact("brief.json")
    validate("bid_brief", brief)
    assert brief["status"] == "approved"
    assert brief["gate1"] == {"approved_by": ACTOR, "at": GATE_AT,
                              "notes": "strong angle set"}
    candidates = brief["win_themes"]["candidates"]
    survivors = [c for c in candidates if c["status"] == "approved"]
    assert [candidates.index(c) + 1 for c in survivors] == list(KEEP_INDEXES)
    assert brief["win_themes"]["approved"] == [c["theme"] for c in survivors]


def test_created_stamped_at_gate(approved):
    pursuit, _ = approved
    assert pursuit.read_artifact("brief.json")["created"] == GATE_AT


def test_gate_approval_unlocks_fork(approved):
    pursuit, _ = approved
    # the exact predicate P6 will check (B22, B5: recorded in the artifact)
    assert pursuit.read_artifact("brief.json")["status"] == "approved"
    assert (pursuit.root / FROZEN_BRIEF).exists()
    records = read_run(pursuit.root / "runs" / "run_0003" / "run.jsonl")
    gates = [r["gate"] for r in records if r["record_type"] == "gate"]
    assert len(gates) == 1
    assert gates[0]["which"] == "gate_1_strategy"
    assert gates[0]["decision"] == "approved"
    assert gates[0]["actor"] == ACTOR
    assert gates[0]["auto_approved"] is False
    assert gates[0]["wait_ms"] == 0


def test_fork_locked_before_gate(pending):
    pursuit, _ = pending
    assert pursuit.read_artifact("brief.json")["status"] == "gate1_pending"
    assert not (pursuit.root / FROZEN_BRIEF).exists()


# ---------------------------------------------------------------- T7 freeze


def test_frozen_copy_byte_identical(approved):
    pursuit, _ = approved
    assert ((pursuit.root / "brief.json").read_bytes()
            == (pursuit.root / FROZEN_BRIEF).read_bytes())


def test_stage_refuses_after_gate(approved):
    pursuit, _ = approved
    before = (pursuit.root / "brief.json").read_bytes()
    report, log_path = bare_strategy_run(pursuit.root.parent, pursuit)
    assert report.status == "refused"
    errors = [r["error"] for r in read_run(log_path)
              if r["record_type"] == "error"]
    assert [e["code"] for e in errors] == ["brief_frozen"]
    assert (pursuit.root / "brief.json").read_bytes() == before


# -------------------------------------------------------------------- edits


def test_approved_with_edits(tmp_path):
    # Edits address candidates by stable id (B37/E2) — index addressing died
    # with the headless-only era.
    edits = {"kill": ["cand_01"],
             "add": [{"theme": "Human angle: co-design the rollout",
                      "rationale": "the lead heard this in discovery"}],
             "edit": [{"candidate_id": "cand_02", "theme": "Edited theme text"}]}
    pursuit, _ = run_strategy_package(tmp_path, gate="approved_with_edits",
                                      edits=edits)
    brief = pursuit.read_artifact("brief.json")
    validate("bid_brief", brief)
    candidates = brief["win_themes"]["candidates"]
    assert candidates[0]["status"] == "killed"
    assert candidates[0]["kill_reason"] == f"killed at Gate 1 by {ACTOR}"
    assert candidates[1]["theme"] == "Edited theme text"
    assert candidates[-1]["theme"] == "Human angle: co-design the rollout"
    assert "cites" not in candidates[-1]  # human-authored: cites optional
    # The human-added candidate continues the id sequence; every candidate
    # carries an id (killed ones keep theirs).
    ids = [c["candidate_id"] for c in candidates]
    assert len(set(ids)) == len(ids)
    assert candidates[-1]["candidate_id"] == f"cand_{len(candidates):02d}"
    assert brief["win_themes"]["approved"] == [
        "Edited theme text", "Human angle: co-design the rollout"]
    records = read_run(pursuit.root / "runs" / "run_0003" / "run.jsonl")
    gate = next(r["gate"] for r in records if r["record_type"] == "gate")
    assert gate["decision"] == "approved_with_edits"
    assert gate["edits_summary"] == "kill:1 add:1 edit:1"


def test_failed_edit_instruction_raises(pending):
    pursuit, _ = pending
    log = _reopen_log(pursuit)
    with pytest.raises(ContractError, match="unknown candidate_id"):
        approve_gate1(pursuit, log, decision="approved_with_edits",
                      actor=ACTOR, at=GATE_AT, edits={"kill": ["cand_99"]})
    # first judge-killed candidate: ids are generation-ordered, keeps first
    killed_id = f"cand_{len(KEEP_INDEXES) + 1:02d}"
    with pytest.raises(ContractError, match="already killed"):
        approve_gate1(pursuit, log, decision="approved_with_edits",
                      actor=ACTOR, at=GATE_AT, edits={"kill": [killed_id]})
    # a failed instruction mutates nothing
    assert pursuit.read_artifact("brief.json")["status"] == "gate1_pending"


# ---------------------------------------------------------------- rejection


def test_rejection_declines_brief(tmp_path):
    pursuit, _ = run_strategy_package(tmp_path, gate="rejected")
    brief = pursuit.read_artifact("brief.json")
    validate("bid_brief", brief)
    assert brief["status"] == "declined"
    assert "approved" not in brief["win_themes"]
    assert brief["gate1"]["approved_by"] == ACTOR  # the decider, B22(12)
    assert brief["created"] == GATE_AT
    assert not (pursuit.root / FROZEN_BRIEF).exists()
    records = read_run(pursuit.root / "runs" / "run_0003" / "run.jsonl")
    gate = next(r["gate"] for r in records if r["record_type"] == "gate")
    assert gate["decision"] == "rejected"


# -------------------------------------------------------------- idempotency


def test_identical_reapproval_converges(approved):
    pursuit, _ = approved
    log_file = pursuit.root / "runs" / "run_0003" / "run.jsonl"
    before_bytes = (pursuit.root / "brief.json").read_bytes()
    before_lines = len(read_run(log_file))
    result = approve_gate1(pursuit, _reopen_log(pursuit), decision="approved",
                          actor=ACTOR, at=GATE_AT)
    assert result.converged is True
    assert (pursuit.root / "brief.json").read_bytes() == before_bytes
    assert len(read_run(log_file)) == before_lines  # log untouched


def test_conflicting_decision_raises(approved):
    pursuit, _ = approved
    with pytest.raises(ContractError, match="already decided"):
        approve_gate1(pursuit, _reopen_log(pursuit), decision="rejected",
                      actor=ACTOR, at=GATE_AT)


def test_auto_approved_consistency_guard(approved):
    pursuit, _ = approved
    log = _reopen_log(pursuit)
    with pytest.raises(ContractError, match="auto_approved"):
        approve_gate1(pursuit, log, decision="approved", actor=ACTOR,
                      at=GATE_AT, auto_approved=True)
    with pytest.raises(ContractError, match="auto_approved"):
        approve_gate1(pursuit, log, decision="auto_approved", actor=ACTOR,
                      at=GATE_AT, auto_approved=False)


def test_malformed_at_raises(pending):
    pursuit, _ = pending
    with pytest.raises(ValueError, match="ISO 8601"):
        approve_gate1(pursuit, _reopen_log(pursuit), decision="approved",
                      actor=ACTOR, at="yesterday")