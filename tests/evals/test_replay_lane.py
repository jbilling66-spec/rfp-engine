"""P32c: the `replay` eval lane — A3's offline half on the release
record. Green on the real bench; red when a stage ignores `exclude`;
a vacuous refusal, never a pass, when the bench has nothing to
withhold (P2-36)."""

import pytest

from engine.evals.release import score_suites
from engine.evals.run import REPLAY_BAR, SUITES, replay_lane


@pytest.fixture(scope="module")
def lane():
    return replay_lane()


def test_the_lane_is_registered_blocking_and_green(lane):
    assert SUITES["replay"] is replay_lane
    assert lane["basis"] == "deterministic" and lane["blocking"] is True
    assert lane["bar"] == REPLAY_BAR
    measures = lane["measures"]
    assert measures["self_exclusion_size"] == 2
    assert measures["excluded_lines"] >= 1
    assert measures["surfaced_excluded_count"] == 0
    assert measures["opened_excluded_count"] == 0
    assert measures["headers_ok"] is True
    assert measures["gates_auto_approved"] is True
    assert measures["no_excluded_card_opened"] is True
    suites, failures = score_suites({"replay": lane})
    assert suites["replay"]["status"] == "pass" and failures == []
    assert "quality not compared" in lane["detail"]


def test_a_stage_that_ignores_exclude_turns_the_lane_red(monkeypatch):
    import engine.research.findings as findings

    real = findings.card_search

    def ignores_exclude(*args, **kwargs):
        kwargs.pop("exclude", None)
        return real(*args, **kwargs)

    monkeypatch.setattr(findings, "card_search", ignores_exclude)
    real_open = findings.targeted_open

    def opens_anyway(*args, **kwargs):
        kwargs.pop("exclude", None)
        return real_open(*args, **kwargs)

    monkeypatch.setattr(findings, "targeted_open", opens_anyway)
    red = replay_lane()
    suites, failures = score_suites({"replay": red})
    assert suites["replay"]["status"] == "fail"
    assert "replay.opened_excluded_count" in failures
    assert "replay.surfaced_excluded_count" in failures
    assert "replay.no_excluded_card_opened" in failures


def test_a_bench_with_nothing_to_withhold_is_a_vacuous_refusal(monkeypatch):
    import engine.evals.replay as bench

    monkeypatch.setattr(bench, "plant_self_sourced_cards",
                        lambda _store, _pid: [])
    empty = replay_lane()
    assert empty["status"] == "fail" and empty["blocking"] is True
    assert "below the declared floor" in empty["detail"]
    assert "self-excluded cards" in empty["detail"]
    assert "measures" not in empty
