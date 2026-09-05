"""Trajectory suite (c9) — the frozen acceptance clause "trajectory
violation detected".

The suite's credibility rests on two halves that must both be proven:
the planted violations really violate (otherwise the assertion could
never fire), and the clean traces are real engine output (otherwise a
pass means nothing). Both are tested here.
"""

import json

import pytest

from engine.evals.trajectory import (CASES_PATH, LIVE_RUNS, TRACES_DIR,
                                     check_assertion, evaluate_trajectory_set,
                                     load_trace)


@pytest.fixture(scope="module")
def report():
    return evaluate_trajectory_set()


def test_a_trace_name_cannot_escape_either_directory():
    """M-20 (P26b-3): the case-supplied name resolves inside one of the
    two trace directories or refuses typed — never a read elsewhere."""
    from engine.contracts import ContractError

    with pytest.raises(ContractError, match="escapes"):
        load_trace("../cases.json")
    with pytest.raises(ContractError, match="escapes"):
        load_trace("/etc/hosts")


def test_a_missing_trace_names_both_directories():
    """No silent fall-through: a name in neither directory is refused
    naming both, so the reader looks in the right place."""
    with pytest.raises(FileNotFoundError) as caught:
        load_trace("nonesuch.jsonl")
    assert str(TRACES_DIR) in str(caught.value)
    assert str(LIVE_RUNS) in str(caught.value)


def test_a_call_without_cost_is_unmeasurable():
    """M-21 (P26b-3): a present call with no cost_usd used to count as
    free, so max_cost_usd held vacuously over it. Now it is the same
    verdict as no calls at all — unmeasurable, never a pass."""
    priced = [{"record_type": "agent_call", "seq": 1, "cost_usd": 0.01}]
    holds, _ = check_assertion(priced, {"assert": "max_cost_usd",
                                        "value": 0.05})
    assert holds is True
    unpriced = priced + [{"record_type": "agent_call", "seq": 2}]
    holds, detail = check_assertion(unpriced, {"assert": "max_cost_usd",
                                               "value": 0.05})
    assert holds is False
    assert "[2]" in detail and "unmeasurable" in detail


def test_cited_not_subset_of_opened_flags():
    """THE acceptance clause. A hand-built violating record list fires
    the assertion; the live trace does not."""
    planted = load_trace("planted_fabricated_citation.jsonl")
    holds, detail = check_assertion(planted, {"assert": "cited_subset_of_opened"})
    assert holds is False
    assert "kb_9631f3268b" in detail, "the detail must name the fabricated id"

    live = load_trace("run_0005.jsonl")
    holds, _ = check_assertion(live, {"assert": "cited_subset_of_opened"})
    assert holds is True


def test_no_excluded_card_opened_twin():
    """G-M: eval-set exclusion stops being a convention and becomes a
    control. The live run excluded a use-restricted card and never
    opened it; the planted trace opens it."""
    live = load_trace("run_0004.jsonl")
    holds, detail = check_assertion(live, {"assert": "no_excluded_card_opened"})
    assert holds is True
    assert "excluded card" in detail

    planted = load_trace("planted_excluded_card_opened.jsonl")
    holds, detail = check_assertion(planted, {"assert": "no_excluded_card_opened"})
    assert holds is False
    assert "kb_restrsev001" in detail


def test_unflagged_tier1_is_visible_only_on_the_trace():
    planted = load_trace("planted_unflagged_tier1.jsonl")
    holds, detail = check_assertion(planted, {"assert": "no_unflagged_tier1"})
    assert holds is False
    assert "tier-1" in detail


def test_emptied_region_produces_a_gap_not_prose():
    planted = load_trace("planted_emptied_region_gap.jsonl")
    holds, _ = check_assertion(planted, {"assert": "gap_emitted"})
    assert holds is True
    # ...and the assertion can say no, so it is not green by construction.
    holds, detail = check_assertion(
        load_trace("run_0005.jsonl"), {"assert": "gap_emitted"})
    assert holds is False
    assert detail == "no gap record emitted"


def test_economy_assertions_can_fail():
    live = load_trace("run_0006.jsonl")
    assert check_assertion(live, {"assert": "max_tool_calls", "value": 40})[0]
    assert not check_assertion(live, {"assert": "max_tool_calls", "value": 1})[0]
    assert check_assertion(live, {"assert": "max_cost_usd", "value": 5.0})[0]
    assert not check_assertion(live, {"assert": "max_cost_usd", "value": 0.0})[0]
    assert check_assertion(live, {"assert": "stage_reached",
                                  "value": "validation"})[0]
    assert not check_assertion(live, {"assert": "stage_reached",
                                      "value": "no_such_stage"})[0]


def test_every_schema_verb_is_implemented():
    """The schema pre-specifies seven verbs and had zero users. An
    unimplemented verb must raise loudly, never pass silently."""
    schema = json.loads(
        (CASES_PATH.parents[2] / "schemas" / "eval-case.schema.json")
        .read_text(encoding="utf-8"))
    verbs = (schema["properties"]["expected"]["properties"]
             ["trajectory_assertions"]["items"]["properties"]["assert"]["enum"])
    trace = load_trace("run_0006.jsonl")
    for verb in verbs:
        check_assertion(trace, {"assert": verb, "value": 999})
    with pytest.raises(ValueError):
        check_assertion(trace, {"assert": "not_a_verb"})


def test_planted_traces_are_planted_and_live_traces_are_live():
    """Fixture integrity in both directions: the planted files are
    committed fixtures under evals/, and the clean cases really point at
    the P8 live run logs (mode 'live', not a rerun under FakeCaller)."""
    assert {p.name for p in TRACES_DIR.glob("*.jsonl")} == {
        "planted_fabricated_citation.jsonl",
        "planted_excluded_card_opened.jsonl",
        "planted_emptied_region_gap.jsonl",
        "planted_unflagged_tier1.jsonl"}
    live = load_trace("run_0005.jsonl")
    start = next(r for r in live if r["record_type"] == "run_start")
    assert start["run"]["mode"] == "live"
    assert (LIVE_RUNS / "run_0005.jsonl").exists()


def test_planted_traces_are_schema_valid_records():
    """A planted violation must be a record the system could legally
    HAVE written — otherwise the suite proves the evaluator catches
    impossible input, which is not the same as catching a real failure.
    (The first cut of these fixtures was not valid; this pins the fix.)"""
    from engine.contracts import check_runlog_payloads, validate

    for path in sorted(TRACES_DIR.glob("*.jsonl")):
        for record in load_trace(path.name):
            validate("run_log", record)
            check_runlog_payloads(record)


def test_suite_passes_and_detects_every_planted_violation(report):
    assert report["failures"] == []
    assert report["pass_rate"] == 1.0
    assert report["n_violation_cases"] == 3
    assert len(report["violations_detected"]) == 3


def test_a_missed_violation_fails_the_suite(tmp_path, monkeypatch):
    """If the evaluator went blind, the suite must fail rather than
    report a clean sweep — the 'scan has not gone blind' guard."""
    import engine.evals.trajectory as mod

    def blind(records, assertion):
        return True, "blind"

    monkeypatch.setattr(mod, "check_assertion", blind)
    report = mod.evaluate_trajectory_set()
    assert report["pass_rate"] < 1.0
    assert any("traj_viol" in f for f in report["failures"])
