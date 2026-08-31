"""Release gates + the record (B40/D4): one scoring implementation grades
every lane from bar vs measures, blocking failures are NAMED, `engine
eval` exits by eval_pass_state, and the mid-phase honest-RED state is
itself pinned — a bar that silently went green would fail here before it
fooled anyone. The acceptance clause "blocking bars gate promotion" is
carried by test_unmet_blocking_bar_exits_nonzero_and_is_named."""

import json

import pytest

from engine.cli.main import main
from engine.evals.release import (build_record, evaluate_gates,
                                  score_suites, write_record)

AT = "2026-08-10T12:00:00Z"
ROOT_MAKEFILE = None  # resolved in the pin test


def _passing_lane(**over):
    lane = {"basis": "deterministic", "blocking": True,
            "bar": {"recall": 0.9}, "measures": {"recall": 0.95}}
    lane.update(over)
    return lane


def test_scoring_names_the_missed_bar_metric():
    suites, failures = score_suites({
        "poison": {"basis": "live_baseline", "blocking": True,
                   "bar": {"recall": 0.98, "precision": 0.85},
                   "measures": {"recall": 0.8667, "precision": 1.0}}})
    assert suites["poison"]["status"] == "fail"
    assert failures == ["poison.recall"]


def test_family_floor_uses_the_weakest_family_never_the_mean():
    measures = {"overall_recall": 0.8,
                "families": {"strong": {"recall": 1.0},
                             "weak": {"recall": 0.5}},
                "false_positives": []}
    suites, failures = score_suites({
        "injection": {"basis": "deterministic", "blocking": True,
                      "bar": {"family_floor": 0.75,
                              "benign_false_positives": 0},
                      "measures": measures}})
    assert suites["injection"]["status"] == "fail"
    assert failures == ["injection.family_floor"]


def test_benign_false_positive_fails_the_floor_bar():
    measures = {"families": {"only": {"recall": 1.0}},
                "false_positives": ["inj_benign_01"]}
    _, failures = score_suites({
        "injection": {"basis": "deterministic", "blocking": True,
                      "bar": {"family_floor": 0.75,
                              "benign_false_positives": 0},
                      "measures": measures}})
    assert failures == ["injection.benign_false_positives"]


def test_stale_baseline_is_a_blocking_state_not_a_silent_pass():
    suites, failures = score_suites({
        "poison": {"basis": "live_baseline", "blocking": True,
                   "status": "baseline_stale",
                   "detail": "prompts moved since the measure"}})
    assert suites["poison"]["status"] == "baseline_stale"
    assert failures == ["poison.baseline_stale"]


def test_advisory_lane_never_blocks():
    _, failures = score_suites({
        "red_team": {"basis": "scripted", "advisory": True,
                     "bar": {"pairwise": 0.8},
                     "measures": {"pairwise": 0.1}}})
    assert failures == []


def test_record_validates_and_not_performed_gates_carry_closers():
    record = build_record({"only": _passing_lane()},
                          engine_version="0.1.0+test", at=AT)
    # build_record schema-validates internally; shape assertions on top:
    assert [g["clause"] for g in record["gates"]] == [1, 2, 3, 4, 5, 6]
    deferred = {g["clause"]: g["closer"] for g in record["gates"]
                if g["status"] == "not_performed"}
    assert deferred == {4: "A3", 5: "A4"}
    assert record["judge_calibration"] == {"status": "not_performed",
                                           "closer": "A4"}
    assert record["eval_pass_state"] is True


def test_unmet_blocking_bar_exits_nonzero_and_is_named(tmp_path,
                                                       monkeypatch):
    """THE acceptance clause: planted failing evidence -> exit 1 with the
    bar named in the record; the green twin -> exit 0."""
    import engine.evals.run as run_mod

    failing = {"poison": lambda: {
        "basis": "live_baseline", "blocking": True,
        "bar": {"recall": 0.98}, "measures": {"recall": 0.5}}}
    monkeypatch.setattr(run_mod, "SUITES", failing)
    code = main(["eval", "--at", AT, "--out", str(tmp_path / "red")])
    assert code == 1
    record = json.loads((tmp_path / "red").glob("*/eval-results.json")
                        .__next__().read_text(encoding="utf-8"))
    assert record["blocking_failures"] == ["poison.recall"]
    assert record["eval_pass_state"] is False
    assert "poison.recall" in next(
        g for g in record["gates"] if g["clause"] == 1)["detail"]

    green = {"poison": lambda: {
        "basis": "live_baseline", "blocking": True,
        "bar": {"recall": 0.98}, "measures": {"recall": 0.99}}}
    monkeypatch.setattr(run_mod, "SUITES", green)
    assert main(["eval", "--at", AT, "--out", str(tmp_path / "green")]) == 0


def test_the_real_lanes_meet_their_bars_on_measured_numbers():
    """Pins the SHAPE of the measured state: both model-scored lanes are
    MEASURED live and both MEET their bars — the B50 re-measure
    (2026-08-14, run_0008/run_0009) read claim-extraction recall 1.0 and
    poison recall 1.0 after the harness-frame fix, closing the red gate
    that stood from cX through P11. The prior red states live in
    evals/*/history.jsonl and the frozen milestone records; B48/B50 carry
    why the numbers moved (the harness frame, not the model, caused every
    remaining miss).

    The bar values are asserted, not just the pass: a green bought by
    moving a bar must fail HERE first, exactly as the red-era twin of
    this test enforced. One-run caveat recorded in B50: prior runs of a
    byte-identical system varied, and the zero-miss bar-shape question
    (A3/A4) stays open."""
    from engine.evals.run import EXTRACTION_BAR, POISON_BAR, SUITES

    assert POISON_BAR == {"recall": 0.98, "precision": 0.85}
    assert EXTRACTION_BAR == {"claim_extraction_recall": 0.98,
                              "claim_over_extraction_rate_max": 0.15}

    lanes = {name: lane() for name, lane in SUITES.items()}
    record = build_record(lanes, engine_version="0.1.0+test", at=AT)
    assert record["eval_pass_state"] is True
    assert record["blocking_failures"] == []

    # Measured, not stale and not absent — the fingerprint guards accept
    # both baselines, so these numbers describe the shipped prompt.
    for name in ("poison", "claim_extraction"):
        assert record["suites"][name]["status"] == "pass"
        assert record["suites"][name]["measures"]

    # Recall did not buy its 1.0 by flagging everything: precision and the
    # extraction controls held.
    assert record["suites"]["poison"]["measures"]["precision"] >= 0.85
    assert record["suites"]["claim_extraction"]["measures"][
        "claim_over_extraction_rate"] == 0.0

    # anonymization holds — the code gates pass offline (E4).
    assert record["suites"]["anonymization"]["status"] == "pass"


def test_single_suite_run_writes_no_record(tmp_path):
    code = main(["eval", "--suite", "anonymization", "--at", AT,
                 "--out", str(tmp_path)])
    assert code == 0
    assert list(tmp_path.rglob("eval-results.json")) == []


def test_unknown_suite_refuses_by_name(tmp_path):
    assert main(["eval", "--suite", "nope", "--out", str(tmp_path)]) == 1


def test_write_record_lands_under_the_engine_version(tmp_path):
    record = build_record({"only": _passing_lane()},
                          engine_version="0.1.0+abc", at=AT)
    path = write_record(record, tmp_path)
    assert path == tmp_path / "0.1.0+abc" / "eval-results.json"
    assert json.loads(path.read_text(encoding="utf-8")) == record


def test_first_record_regression_clauses_answer_honestly():
    gates = evaluate_gates({}, [], prior=None)
    for clause in (2, 3):
        gate = next(g for g in gates if g["clause"] == clause)
        assert gate["status"] == "pass"
        assert "first record" in gate["detail"]


def test_make_eval_invokes_the_cli():
    # The liveness pin (B34(24) shape): if the Makefile ever stops
    # invoking the harness CLI, the surface loses its proof.
    from pathlib import Path
    makefile = (Path(__file__).resolve().parents[2] / "Makefile").read_text(
        encoding="utf-8")
    assert "-m engine eval" in makefile
    assert "exit 1" not in makefile.split("eval:")[1].split("lock:")[0]


# --------------------------------------------------- diagnostic export (C6)

def test_a_baseline_without_cause_data_says_so_rather_than_looking_complete():
    """P11-C6, kept at unit level after the C8 run.

    Until the diagnostic run landed, both real baselines exercised this
    branch. They no longer do — so the branch is driven with a synthetic
    stale baseline instead of deleted, because it is still exactly what
    any future stale or partial baseline produces.

    Silence about a missing key reads exactly like "there were no misses",
    and P10-F16 is the story of someone reading the first when the truth
    was the second."""
    from engine.evals.run import _with_diagnostics

    entry = _with_diagnostics({"measures": {"recall": 0.8667}}, {})
    assert entry["measures"]["diagnostics_absent"] == [
        "misses", "miss_detail", "causes"]
    assert "predates the cause instrumentation" in entry["detail"]
    assert not any(k in entry["measures"]
                   for k in ("misses", "miss_detail", "causes"))

    # The half-populated shape: miss_detail present, `causes` absent — the
    # state both baselines were in before the run, where the causes on
    # record were computed without the parser's drop warnings.
    half = _with_diagnostics(
        {"measures": {}},
        {"misses": ["a"], "miss_detail": {"a": {"cause": "not_extracted"}}})
    assert half["measures"]["diagnostics_absent"] == ["causes"]
    assert "without the parser's drop warnings" in half["detail"]


def test_the_real_lanes_now_carry_their_cause_data():
    """The frozen-row clause, read off the shipped record: every miss in
    BOTH model-scored suites carries a recorded cause, and neither lane
    claims any diagnostic is absent."""
    from engine.evals.run import extraction_lane, poison_lane

    for lane in (poison_lane(), extraction_lane()):
        measures = lane["measures"]
        assert "diagnostics_absent" not in measures
        assert "misses" in measures and "causes" in measures
        # counts reconcile: every miss is described, nothing invented
        assert sorted(measures["miss_detail"]) == sorted(measures["misses"])
        assert sum(measures["causes"].values()) == len(measures["misses"])
        for detail in measures["miss_detail"].values():
            assert detail["cause"], "a miss with no cause is the old state"
            assert detail["unmarked_warnings"] == []


def test_a_baseline_with_cause_data_exports_it_and_claims_no_absence():
    """The other shape, so the post-run record is pinned before the run —
    otherwise the only proof it works arrives after the money is spent."""
    from engine.evals.run import _with_diagnostics

    complete = {"misses": ["extract_hedge_001"],
                "miss_detail": {"extract_hedge_001": {
                    "cause": "dropped_verbatim", "warnings": ["…"],
                    "wire_excerpt": '{"claims": [...]}', "output_tokens": 110}},
                "causes": {"dropped_verbatim": 1}}
    entry = _with_diagnostics({"measures": {}}, complete)

    assert entry["measures"]["causes"] == {"dropped_verbatim": 1}
    assert entry["measures"]["misses"] == ["extract_hedge_001"]
    assert entry["measures"]["miss_detail"]["extract_hedge_001"][
        "wire_excerpt"], "the evidence must reach the record, not just the DB"
    assert "diagnostics_absent" not in entry["measures"]
    assert "detail" not in entry


def test_exporting_diagnostics_cannot_move_a_bar_or_a_verdict():
    """The frozen row says no bar VALUE moves. Scoring reads `bar`, never
    `measures`, so adding measure keys is inert by construction — asserted
    rather than assumed, because 'inert by construction' is exactly the
    kind of claim that stops being true quietly."""
    from engine.evals.release import score_suites

    bar = {"recall": 0.98}
    lean = {"basis": "live_baseline", "blocking": True, "bar": dict(bar),
            "measures": {"recall": 0.8667}}
    rich = {"basis": "live_baseline", "blocking": True, "bar": dict(bar),
            "measures": {"recall": 0.8667, "misses": ["a", "b"],
                         "miss_detail": {"a": {"cause": "not_extracted"}},
                         "causes": {"not_extracted": 1}}}

    lean_suites, lean_failures = score_suites({"poison": lean})
    rich_suites, rich_failures = score_suites({"poison": rich})
    assert lean_failures == rich_failures == ["poison.recall"]
    assert lean_suites["poison"]["status"] == rich_suites["poison"]["status"]
