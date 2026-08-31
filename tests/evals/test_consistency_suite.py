"""The consistency, drafter and red-team lanes (c8).

These are the EVAL_SUITE rows whose measurement is a MODEL judgement, so
the property under test is honesty: what can be measured offline IS, and
what cannot says so rather than reporting a scripted number as if it
described the model.
"""

import pytest

from engine.evals.consistency import (CASES_PATH, CROSS_REF_CASES,
                                      evaluate_consistency_set)
from engine.evals.run import consistency_lane, drafter_lane, red_team_lane


@pytest.fixture(scope="module")
def report():
    return evaluate_consistency_set()


def test_the_code_half_is_measured_for_real(report):
    assert report["n_code_detectable"] == len(CROSS_REF_CASES)
    assert report["code_detection_rate"] == 1.0
    assert report["misses"] == []


def test_the_code_half_can_fail():
    """A suite that cannot fail proves nothing: flip an expectation and
    the lane must report the miss."""
    import engine.evals.consistency as mod

    original = mod.CROSS_REF_CASES
    try:
        mod.CROSS_REF_CASES = [{**original[0], "must_flag": False}] + list(
            original[1:])
        broken = evaluate_consistency_set()
    finally:
        mod.CROSS_REF_CASES = original
    assert broken["code_detection_rate"] < 1.0
    assert "consistency_code_001" in broken["misses"]


def test_the_code_cases_carry_both_directions():
    """Controls matter as much as conflicts: a checker that flags
    everything would pass a conflicts-only set."""
    flagging = [c for c in CROSS_REF_CASES if c["must_flag"]]
    controls = [c for c in CROSS_REF_CASES if not c["must_flag"]]
    assert flagging and controls
    assert any("gated_skipped" in str(c["sections"]) for c in controls), (
        "a decided absence is not a dangling reference")


def test_the_contradiction_set_is_twenty_cases_with_controls(report):
    """B34(8)'s 20-case set, authored and awaiting a live measurement."""
    from engine.evals.cases import load_cases

    cases = load_cases(CASES_PATH)
    assert len(cases) == 20
    conflicts = [c for c in cases if c["expected"]["must_flag"]]
    controls = [c for c in cases if not c["expected"]["must_flag"]]
    assert len(conflicts) == 16 and len(controls) == 4
    assert sum(1 for c in cases if c["held_out"]) / len(cases) >= 0.20


def test_the_contradiction_cases_are_genuinely_two_statements():
    """Fixture integrity: each case must actually carry a PAIR, or the
    checker has nothing to compare."""
    from engine.evals.cases import load_cases

    for case in load_cases(CASES_PATH):
        halves = case["input"]["prompt_context"].split("\n---\n")
        assert len(halves) == 2, case["case_id"]
        assert halves[0].strip() and halves[1].strip()


def test_the_model_half_is_counted_but_not_scored(report):
    """Scoring it under a scripted caller would report the script's
    answer — the fiction B33(1) refuses for the poison set."""
    assert report["n_model_only"] == 20
    assert "model_detection_rate" not in report


def test_the_consistency_lane_says_what_is_unmeasured():
    entry = consistency_lane()
    assert entry["measures"]["code_detection_rate"] == 1.0
    assert "awaiting a live measurement" in entry["detail"]


def test_advisory_lanes_never_block():
    """B34(9): no gate consumes a red-team score. An advisory lane that
    is unmeasured must not hold promotion hostage — but it must still
    appear on the record, so nobody mistakes silence for a pass."""
    from engine.evals.release import score_suites

    lanes = {"drafter": drafter_lane(), "red_team": red_team_lane()}
    suites, failures = score_suites(lanes)
    assert failures == []
    for name in lanes:
        assert suites[name]["status"] == "not_measured_live"
        assert suites[name]["advisory"] is True
        assert suites[name]["detail"], "an unmeasured lane must say why"


def test_the_drafter_row_names_what_covers_its_other_halves():
    """EVAL_SUITE's drafter row is rubric + voice + citation
    faithfulness. Two of the three ARE measured elsewhere; saying so is
    the difference between a deferral and a gap."""
    detail = drafter_lane()["detail"]
    assert "voice lane" in detail and "trajectory" in detail
