"""schemas/run-log.schema.json's gate block gains `notes` (P26a Group D,
P1-15): the decider's rationale rides the append-only run log. Optional
— every existing gate line still validates — and closed: a second
unknown key still refuses."""

import pytest

from engine.contracts import ContractError, validate

BASE = {"run_id": "run_0001", "pursuit_id": "pur_n", "seq": 1,
        "ts": "2026-09-02T10:00:00Z", "record_type": "gate", "stage": "gate_0",
        "gate": {"which": "gate_0_intake", "decision": "rejected",
                 "actor": "Rae", "auto_approved": False, "wait_ms": 0}}


def test_notes_validate_and_stay_optional():
    validate("run_log", {**BASE, "gate": {**BASE["gate"],
                                          "notes": "Re-read the deadline."}})
    validate("run_log", BASE)


def test_the_gate_block_stays_closed():
    with pytest.raises(ContractError):
        validate("run_log", {**BASE, "gate": {**BASE["gate"], "notes": 5}})
    with pytest.raises(ContractError):
        validate("run_log", {**BASE, "gate": {**BASE["gate"],
                                              "rationale": "x"}})
