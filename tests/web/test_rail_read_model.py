"""P30a (B139): the detail rail's read model — the station number
(`stage_n` of `stage_count`) on the board row and the detail, the
decided gates read from the artifacts' own records (`brief.gate0`,
`brief.gate1`, `plan.gate2`), and the open-gap count the board already
computes, shared with the detail. Three-state throughout: a figure
whose source is absent is absent from the payload."""

import json

from engine.web import state
from engine.workspace import PursuitDir

AT = "2026-10-03T09:00:00Z"
GATE0 = {"approved_by": "fixture-lead", "at": AT, "request_sha256": "0" * 64,
         "notes": "assumptions confirmed"}
GATE1 = {"approved_by": "fixture-partner", "at": AT,
         "request_sha256": "1" * 64}


def _gate1_pursuit(tmp_path, pid="pur_rail", **brief_extra):
    """A pursuit waiting at Gate 1: brief present, intake and Gate 0
    checkpointed, no frozen brief yet."""
    ws = tmp_path / "ws"
    pursuit = PursuitDir(ws, pid)
    brief = {"pursuit_id": pid, "status": "gate1_pending", **brief_extra}
    (pursuit.root / "brief.json").write_text(json.dumps(brief))
    (pursuit.root / "checkpoints").mkdir(exist_ok=True)
    for stage in ("bid_brief", "gate_0"):
        pursuit.checkpoint(stage, {"decision": "approved"})
    return ws, pursuit


def _plan(pursuit, gaps=(), **extra):
    plan = {"pursuit_id": pursuit.pursuit_id, "status": "gate2_pending",
            "sections": [{"section_id": "s1", "title": "One",
                          "gaps": [{"gap_id": f"g{i}", "status": s}
                                   for i, s in enumerate(gaps)]}],
            **extra}
    (pursuit.root / "plan.json").write_text(json.dumps(plan))


def _row(ws, pid="pur_rail"):
    return next(r for r in state.board(ws) if r["pursuit_id"] == pid)


def test_the_detail_names_the_decided_gates_from_the_records(tmp_path):
    ws, pursuit = _gate1_pursuit(tmp_path, gate0=GATE0, gate1=GATE1)
    _plan(pursuit)  # a plan with no gate2 record yet
    gates = state.detail(ws, "pur_rail")["gates"]
    assert gates == {"gate_0": {"by": "fixture-lead", "at": AT},
                     "gate_1": {"by": "fixture-partner", "at": AT}}
    assert "gate_2" not in gates
    assert all("notes" not in g for g in gates.values())


def test_a_gate2_record_on_the_plan_is_read_too(tmp_path):
    ws, pursuit = _gate1_pursuit(tmp_path, gate0=GATE0)
    _plan(pursuit, gate2={"approved_by": "fixture-lead", "at": AT,
                          "request_sha256": "2" * 64, "gates_collapsed": True})
    gates = state.detail(ws, "pur_rail")["gates"]
    assert set(gates) == {"gate_0", "gate_2"}
    assert gates["gate_2"] == {"by": "fixture-lead", "at": AT}


def test_no_gate_record_means_no_gates_key(tmp_path):
    ws, _ = _gate1_pursuit(tmp_path)
    assert "gates" not in state.detail(ws, "pur_rail")


def test_the_station_number_is_the_servers_and_absent_off_the_pipeline(tmp_path):
    ws, pursuit = _gate1_pursuit(tmp_path)
    row = _row(ws)
    assert (row["stage"], row["stage_n"], row["stage_count"]) == ("gate_1", 4, 9)
    d = state.detail(ws, "pur_rail")
    assert (d["stage_n"], d["stage_count"]) == (4, 9)
    assert state.PIPELINE[-1] == "review" and len(state.PIPELINE) == 9
    # declined: off the pipeline, no station
    brief = json.loads((pursuit.root / "brief.json").read_text())
    brief["status"] = "declined"
    (pursuit.root / "brief.json").write_text(json.dumps(brief))
    row = _row(ws)
    assert row["stage"] == "declined" and "stage_n" not in row
    assert "stage_n" not in state.detail(ws, "pur_rail")
    # corrupt: the override wins, no station
    (pursuit.root / "plan.json").write_text("{not json")
    row = _row(ws)
    assert row["stage"] == "corrupt" and "stage_n" not in row


def test_open_gaps_on_the_detail_equals_the_boards(tmp_path):
    ws, pursuit = _gate1_pursuit(tmp_path)
    assert "open_gaps" not in state.detail(ws, "pur_rail")  # no plan yet
    _plan(pursuit, gaps=("open", "pinged", "answered", "omit_approved"))
    assert _row(ws)["open_gaps"] == 2
    assert state.detail(ws, "pur_rail")["open_gaps"] == 2
