"""P0-9 (P26a Group E): clauses 2–3 of the release gate compare MEASURED
numbers against the latest prior record and CAN fail; a failure without a
named owner's written override flips eval_pass_state and the CLI's exit
code; the prior is chosen by generated_at, never by directory name; a
missing measure is not_performed with its closer; a record is archived,
never clobbered; and the two bar asymmetries the sweep found (P2-32,
P2-33) are closed."""

import json
from pathlib import Path

import pytest

from engine.cli.main import main
from engine.evals.release import (
    TRAJECTORY_REGRESSION_TOLERANCE,
    build_record,
    evaluate_gates,
    latest_prior,
    score_suites,
    write_record,
)

AT = "2026-09-02T12:00:00Z"


def _suites(cost=1.0, calls=3.0, recall=0.8, gap=0.05):
    return {
        "trajectory": {"status": "pass", "basis": "deterministic",
                       "blocking": True, "bar": {},
                       "measures": {"cost_per_section": cost,
                                    "tool_calls_per_section": calls}},
        "mapper": {"status": "pass", "basis": "deterministic",
                   "blocking": False, "bar": {},
                   "measures": {"recall_at_5": recall,
                                "false_gap_rate": gap}},
    }


def _prior(**kw):
    return {"engine_version": "0.2.0+prior", "generated_at": AT,
            "mode": "regression_bench", "hold_constant": {"config_digest": "x"},
            "suites": _suites(**kw)}


def _clause(gates, n):
    return next(g for g in gates if g["clause"] == n)


def test_clauses_two_and_three_fail_against_a_better_prior():
    gates = evaluate_gates(_suites(cost=1.5, calls=3.0, recall=0.7,
                                   gap=0.10), [], prior=_prior())
    two, three = _clause(gates, 2), _clause(gates, 3)
    assert two["status"] == "fail"
    assert "trajectory.cost_per_section 1.5 vs prior 1.0 WORSE" in two["detail"]
    assert three["status"] == "fail"
    assert "mapper.recall_at_5 0.7 vs prior 0.8 WORSE" in three["detail"]
    assert "mapper.false_gap_rate 0.1 vs prior 0.05 WORSE" in three["detail"]


def test_within_tolerance_and_equal_pass_and_the_prior_is_named():
    within = 1.0 * (1 + TRAJECTORY_REGRESSION_TOLERANCE) - 0.01
    gates = evaluate_gates(_suites(cost=within), [], prior=_prior())
    assert _clause(gates, 2)["status"] == "pass"
    assert "against 0.2.0+prior" in _clause(gates, 2)["detail"]
    assert _clause(gates, 3)["status"] == "pass"
    # clause 3 is strict: any worse fails
    gates = evaluate_gates(_suites(gap=0.0501), [], prior=_prior())
    assert _clause(gates, 3)["status"] == "fail"


def test_hold_constant_drift_annotates_and_never_blocks():
    gates = evaluate_gates(_suites(), [], prior=_prior(),
                           hold_constant={"config_digest": "y",
                                          "kb_snapshot": "k"})
    assert _clause(gates, 2)["status"] == "pass"
    assert "hold_constant drift noted: config_digest" in _clause(gates, 2)["detail"]


def test_a_missing_measure_is_not_performed_with_a_closer():
    suites = _suites()
    del suites["trajectory"]["measures"]["cost_per_section"]
    del suites["trajectory"]["measures"]["tool_calls_per_section"]
    gates = evaluate_gates(suites, [], prior=_prior())
    two = _clause(gates, 2)
    assert two["status"] == "not_performed" and two["closer"]
    assert "trajectory.cost_per_section" in two["detail"]


def test_latest_prior_picks_by_generated_at_not_directory_name(tmp_path):
    for version, at in (("0.1.0+0c8d709", "2026-08-11T03:00:00Z"),
                        ("0.1.0+938df5b", "2026-08-14T08:00:00Z"),
                        ("0.2.0+current", "2026-09-02T00:00:00Z")):
        d = tmp_path / version
        d.mkdir()
        (d / "eval-results.json").write_text(json.dumps({
            "engine_version": version, "generated_at": at,
            "mode": "regression_bench", "suites": {}}))
    prior = latest_prior(tmp_path, exclude_version="0.2.0+current")
    assert prior["engine_version"] == "0.1.0+938df5b"
    assert latest_prior(tmp_path / "nowhere") is None


def test_an_override_promotes_a_failed_clause_and_is_on_the_record(
        monkeypatch):
    lanes = _suites(cost=2.0)
    monkeypatch.setattr("engine.evals.release.hold_constant", lambda v: {
        "engine_version": v, "config_digest": "cfg:test", "kb_snapshot": "kb@t",
        "model_pins": {"fast": "m", "mid": "m", "frontier": "m"},
        "prompt_version": "cfg:test", "judge_model": None,
        "rate_card_version": "unset"})
    without = build_record(lanes, engine_version="0.3.0+t", at=AT,
                           prior=_prior())
    assert without["eval_pass_state"] is False
    with_it = build_record(lanes, engine_version="0.3.0+t", at=AT,
                           prior=_prior(),
                           overrides=[{"gate_clause": 2, "by": "Owner",
                                       "at": AT, "note": "accepted cost"}])
    assert with_it["eval_pass_state"] is True
    assert with_it["overrides"][0]["by"] == "Owner"


def test_cli_exits_nonzero_on_a_regression_without_an_override(
        tmp_path, monkeypatch):
    import engine.evals.run as run_mod
    out = tmp_path / "rel"
    (out / "0.2.0+prior").mkdir(parents=True)
    (out / "0.2.0+prior" / "eval-results.json").write_text(
        json.dumps(_prior()))
    monkeypatch.setattr(run_mod, "SUITES", {
        name: (lambda e=entry: e) for name, entry in _suites(cost=5.0).items()})
    assert main(["eval", "--at", AT, "--out", str(out)]) == 1
    assert main(["eval", "--at", AT, "--out", str(out), "--override", "2",
                 "--by", "Owner", "--note", "accepted"]) == 0
    assert main(["eval", "--at", AT, "--out", str(out), "--override", "2"]) == 1


def test_write_record_archives_the_prior_instead_of_clobbering(tmp_path):
    first = {**_prior(), "engine_version": "0.3.0+x", "generated_at": AT}
    write_record(first, tmp_path)
    second = {**first, "generated_at": "2026-09-03T00:00:00Z"}
    path = write_record(second, tmp_path)
    assert json.loads(path.read_text())["generated_at"] == "2026-09-03T00:00:00Z"
    history = list((tmp_path / "0.3.0+x" / "history").glob("*.json"))
    assert len(history) == 1
    assert json.loads(history[0].read_text())["generated_at"] == AT


def test_a_missing_measure_fails_a_ceiling_bar_and_a_status_lane_is_graded():
    suites, failures = score_suites({
        "mapper": {"blocking": True, "bar": {"false_gap_rate_max": 0.05},
                   "measures": {}},                                   # P2-32
        "voice": {"blocking": True, "status": "pass",
                  "bar": {"recall": 0.9}, "measures": {"recall": 0.5}},  # P2-33
    })
    assert "mapper.false_gap_rate" in failures
    assert suites["voice"]["status"] == "fail" and "voice.recall" in failures
