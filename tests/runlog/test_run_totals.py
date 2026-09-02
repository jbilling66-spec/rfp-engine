"""O6's compute-vs-human-wait split, and the wall-clock span (c12).

All three fields were schema-declared with no writer, which left
cycle_time_days and compute_vs_human_wait dormant. They are computed in
the WRITER, not by a caller, so the footer reconciles from the lines it
actually emitted — a caller asserting its own totals is the shape that
lets a footer disagree with its record.
"""

import json

from engine.llm import FakeCaller, TracedCaller
from engine.runlog import RunLogger, read_run


def _logger(tmp_path):
    log = RunLogger(tmp_path / "pur_x", run_id="run_0001", pursuit_id="pur_x")
    log.run_start(mode="dry_run", engine_version="0.1.0",
                  config={"k": "v"}, kb_snapshot="kb@test")
    return log


def _footer(log):
    """Close the run and read the rollup it wrote."""
    log.run_end(status="completed")
    return read_run(log.path)[-1]["run"]["totals"]


def test_compute_ms_sums_agent_call_durations(tmp_path):
    log = _logger(tmp_path)
    caller = TracedCaller(FakeCaller({"a": "one", "b": "two"}), log)
    caller.call("a", tier="mid", prompt="p")
    caller.call("b", tier="mid", prompt="p")
    totals = _footer(log)

    records = read_run(log.path)
    calls = [r for r in records if r["record_type"] == "agent_call"]
    assert len(calls) == 2
    assert all("duration_ms" in c for c in calls), (
        "duration_ms was schema-declared with no writer — compute_ms has "
        "no source without it")
    assert totals["compute_ms"] == sum(c["duration_ms"] for c in calls)


def test_human_wait_ms_sums_gate_waits_not_compute(tmp_path):
    log = _logger(tmp_path)
    log.emit("gate", stage="gate_2",
             gate={"which": "gate_2_plan", "decision": "approved",
                   "actor": "reviewer", "wait_ms": 90_000})
    log.emit("gate", stage="gate_1",
             gate={"which": "gate_1_strategy", "decision": "approved",
                   "actor": "reviewer", "wait_ms": 30_000})
    totals = _footer(log)
    assert totals["human_wait_ms"] == 120_000
    # The whole point of the split: human latency never lands in compute.
    assert totals["compute_ms"] == 0


def test_wall_ms_is_the_runs_own_span_and_never_negative(tmp_path):
    log = _logger(tmp_path)
    log.emit("stage_start", stage="drafting")
    totals = _footer(log)
    assert totals["wall_ms"] >= 0
    records = read_run(log.path)
    assert records[0]["ts"] <= records[-1]["ts"]


def test_wall_ms_covers_compute(tmp_path):
    """The identity that makes the split readable: a run cannot spend
    more time computing than it existed for."""
    log = _logger(tmp_path)
    caller = TracedCaller(FakeCaller({"a": "one"}), log)
    caller.call("a", tier="mid", prompt="p")
    totals = _footer(log)
    assert totals["compute_ms"] <= totals["wall_ms"] + 1  # ms rounding


def test_totals_survive_a_reopened_logger(tmp_path):
    """The replay path accumulates the same fields — a resumed run must
    not forget the compute it already spent."""
    log = _logger(tmp_path)
    caller = TracedCaller(FakeCaller({"a": "one"}), log)
    caller.call("a", tier="mid", prompt="p")
    first = read_run(log.path)
    spent = sum(r.get("duration_ms", 0) for r in first
                if r["record_type"] == "agent_call")

    reopened = RunLogger(tmp_path / "pur_x", run_id="run_0001", resume=True,
                         pursuit_id="pur_x")
    reopened.emit("gate", stage="gate_2",
                  gate={"which": "gate_2_plan", "decision": "approved",
                        "actor": "reviewer", "wait_ms": 5_000})
    totals = _footer(reopened)
    assert totals["compute_ms"] == spent
    assert totals["human_wait_ms"] == 5_000


def test_explicit_totals_extra_still_wins(tmp_path):
    """run_end(**totals_extra) is the documented seam; a caller with a
    better number must be able to say so."""
    log = _logger(tmp_path)
    log.run_end(status="completed", wall_ms=42)
    assert read_run(log.path)[-1]["run"]["totals"]["wall_ms"] == 42


def test_footer_validates_against_the_contract(tmp_path):
    log = _logger(tmp_path)
    caller = TracedCaller(FakeCaller({"a": "one"}), log)
    caller.call("a", tier="mid", prompt="p")
    log.run_end(status="completed")
    footer = json.loads(log.path.read_text(encoding="utf-8").splitlines()[-1])
    for field in ("wall_ms", "compute_ms", "human_wait_ms"):
        assert isinstance(footer["run"]["totals"][field], int)
