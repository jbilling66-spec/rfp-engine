"""Run-log discipline for the strategy run (P5 acceptance: gate event in
run log): exact stage-line sequence, both frontier calls under win_themes,
the gate line schema-valid with the full payload, gapless seq, totals that
count only the model calls, and the awaiting_gate status for an ungated
run."""

import pytest

from engine.contracts import validate
from engine.runlog import assert_seq_gapless, read_run
from tests.strategy.fixtures.strategies import ACTOR, run_strategy_package


@pytest.fixture(scope="module")
def gated(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("runlog_gated")
    return run_strategy_package(tmp)


@pytest.fixture(scope="module")
def ungated(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("runlog_ungated")
    return run_strategy_package(tmp, gate=None)


def _records(pursuit):
    return read_run(pursuit.root / "runs" / "run_0003" / "run.jsonl")


def test_every_line_valid_and_seq_gapless(gated):
    pursuit, _ = gated
    records = _records(pursuit)
    for record in records:
        validate("run_log", record)
    assert_seq_gapless(records)


def test_stage_line_sequence(gated):
    pursuit, _ = gated
    shape = [(r["record_type"], r.get("stage")) for r in _records(pursuit)]
    assert shape == [
        ("run_start", None),
        ("stage_start", "win_themes"),
        ("agent_call", "win_themes"),
        ("agent_call", "win_themes"),
        ("artifact", "win_themes"),
        ("stage_end", "win_themes"),
        ("stage_start", "gate_1"),
        ("artifact", "gate_1"),      # brief.json
        ("artifact", "gate_1"),      # brief.frozen.json, same sha256
        ("gate", "gate_1"),
        ("stage_end", "gate_1"),
        ("run_end", None),
    ]


def test_agent_calls_are_the_frontier_strategist(gated):
    pursuit, _ = gated
    calls = [r for r in _records(pursuit) if r["record_type"] == "agent_call"]
    assert [c["agent"] for c in calls] == ["win_theme_strategist"] * 2
    assert all(c["model_tier"] == "frontier" for c in calls)
    assert all(c["model"] == "fake-frontier-1" for c in calls)


def test_gate_event_shape(gated):
    pursuit, _ = gated
    gates = [r for r in _records(pursuit) if r["record_type"] == "gate"]
    assert len(gates) == 1
    assert gates[0]["gate"] == {"which": "gate_1_strategy",
                                "decision": "approved", "actor": ACTOR,
                                "auto_approved": False, "wait_ms": 0}


def test_frozen_artifact_records_share_one_sha(gated):
    pursuit, _ = gated
    arts = [r["artifact"] for r in _records(pursuit)
            if r["record_type"] == "artifact" and r.get("stage") == "gate_1"]
    assert [a["kind"] for a in arts] == ["bid_brief", "bid_brief"]
    assert arts[0]["sha256"] == arts[1]["sha256"]  # byte-equal freeze (T7)
    assert arts[0]["path"].endswith("brief.json")
    assert arts[1]["path"].endswith("brief.frozen.json")


def test_totals_count_only_the_model_calls(gated):
    pursuit, _ = gated
    records = _records(pursuit)
    footer = records[-1]
    assert footer["record_type"] == "run_end"
    assert footer["run"]["status"] == "completed"
    assert footer["run"]["totals"]["agent_calls"] == 2  # gate moves no total
    calls = [r for r in records if r["record_type"] == "agent_call"]
    assert footer["run"]["totals"]["cost_usd"] == round(
        sum(c["cost_usd"] for c in calls), 6)


def test_ungated_run_ends_awaiting_gate(ungated):
    pursuit, _ = ungated
    records = _records(pursuit)
    assert records[-1]["run"]["status"] == "awaiting_gate"
    assert not [r for r in records if r["record_type"] == "gate"]