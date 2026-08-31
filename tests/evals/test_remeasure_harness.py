"""The P17 funded re-measure harness, proven offline (B75§1a): the
whole arm — corpus copy, injected enrichment, real mapper eval, delta
vs the recorded baseline with regressions named — runs with a scripted
questioner and zero spend (the rebaseline arm's injected-caller
property). A scripted run can be REPORTED but never RECORDED as the
measured baseline — refused by name."""

import pytest

from engine.evals.remeasure import (
    RECORDED_BASELINE,
    RemeasureRefused,
    remeasure_mapper,
)


def test_empty_enrichment_reproduces_the_baseline_exactly(tmp_path):
    """questioner returning nothing = the committed corpus verbatim —
    the measured rates must equal the recorded baseline to the digit
    (determinism + the B75§4a unmoved claim, through the harness)."""
    result = remeasure_mapper(lambda card, body: [],
                              workspace=tmp_path / "ws")
    assert result["mode"] == "scripted"
    assert result["measured"] == RECORDED_BASELINE
    assert all(d == 0 for d in result["delta"].values())
    assert result["regressions"] == []
    assert result["enriched_cards"] == 0
    assert result["recorded"] is False


def test_enrichment_flows_through_and_regressions_are_named(tmp_path):
    """A questioner that actively PLANTS distinctive noise tokens on
    every card shifts the idf universe; whatever moves, the report
    carries the delta and names any wrong-direction rate — a worse
    number is reported, never absorbed."""
    def noisy(card, body):
        return [f"zzq{card['kb_id'][-6:]} noise question form"]

    result = remeasure_mapper(noisy, workspace=tmp_path / "ws")
    assert result["enriched_cards"] > 0
    assert set(result["delta"]) == set(RECORDED_BASELINE)
    for key in result["regressions"]:
        assert key in RECORDED_BASELINE


def test_recording_a_scripted_run_is_refused(tmp_path):
    with pytest.raises(RemeasureRefused, match="wearing the model's"):
        remeasure_mapper(lambda c, b: [], workspace=tmp_path / "ws",
                         record=True, live=False)
    assert not (tmp_path / "result.json").exists()


def test_live_recording_writes_the_result_file(tmp_path):
    """The write path, exercised offline to a tmp path (the rebaseline
    arm's precedent) — only the operator's live assertion gates it."""
    out = remeasure_mapper(lambda c, b: [], workspace=tmp_path / "ws",
                           live=True, record=True,
                           record_path=tmp_path / "result.json")
    assert out["recorded"] is True
    assert (tmp_path / "result.json").exists()
