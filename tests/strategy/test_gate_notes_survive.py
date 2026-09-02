"""P1-15 (P26a Group D): a gate decision's notes are on the run log —
append-only, so a Gate-0 rejection's mandatory rationale is no longer
discarded on receipt and a Gate-2 rejection's survives the next
decision; Gate 1 gains the rule the other two had."""

import pytest

from engine.contracts import ContractError
from engine.intake.gate import approve_gate0
from engine.llm import effective_config
from engine.runlog import RunLogger, read_run
from engine.strategy import approve_gate1
from engine.version import engine_version
from tests.intake.fixtures.packages import RAMBLE, run_package
from tests.strategy.fixtures.strategies import run_strategy_package

AT = "2026-09-02T10:00:00"


def _log(pursuit):
    log = RunLogger(pursuit.root, pursuit.new_run_id(), pursuit.pursuit_id)
    log.run_start(mode="dry_run", engine_version=engine_version(),
                  config=effective_config(), kb_snapshot="kb@empty")
    return log


def _gate_lines(log):
    return [r["gate"] for r in read_run(log.path)
            if r.get("record_type") == "gate"]


def test_gate0_rejection_notes_survive_in_the_run_log_and_checkpoint(
        tmp_path):
    pursuit, _ = run_package(tmp_path, "pdf", ramble=RAMBLE)
    log = _log(pursuit)
    approve_gate0(pursuit, log, decision="rejected", actor="Rae Reviewer",
                  at=AT, notes="Re-read the deadline.")
    log.run_end(status="completed")
    gate = _gate_lines(log)[-1]
    assert gate["decision"] == "rejected"
    assert gate["notes"] == "Re-read the deadline."
    assert pursuit.checkpoint_payload("gate_0_rejection")["notes"] == \
        "Re-read the deadline."


def test_gate0_approval_notes_ride_the_gate_line_too(tmp_path):
    pursuit, _ = run_package(tmp_path, "pdf", ramble=RAMBLE)
    log = _log(pursuit)
    approve_gate0(pursuit, log, decision="approved", actor="Rae", at=AT,
                  notes="read it")
    assert _gate_lines(log)[-1]["notes"] == "read it"


def test_gate1_decline_requires_notes_and_records_them(tmp_path):
    pursuit, _ = run_strategy_package(tmp_path, gate=None)
    log = _log(pursuit)
    with pytest.raises(ContractError, match="gate_1 rejection requires notes"):
        approve_gate1(pursuit, log, decision="rejected", actor="Rae", at=AT)
    approve_gate1(pursuit, log, decision="rejected", actor="Rae", at=AT,
                  notes="Not our market.")
    assert _gate_lines(log)[-1]["notes"] == "Not our market."
