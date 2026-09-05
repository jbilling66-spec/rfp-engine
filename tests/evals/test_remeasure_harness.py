"""The P17 funded re-measure harness, proven offline (B75§1a): the
whole arm — corpus copy, injected enrichment, real mapper eval, delta
vs the recorded baseline with regressions named — runs with a scripted
questioner and zero spend (the rebaseline arm's injected-caller
property). A scripted run can be REPORTED but never RECORDED as the
measured baseline — refused by name.

P2-37 (P26b-3): "live" is gated, not declared — RFP_LIVE=1 plus a
questioner built over a traced LiveCaller — and the baseline is read
from the shipped, drift-tested evals/mapper/recorded.json, never a
hand copy.
"""

import json

import pytest

from engine.evals.remeasure import (
    RemeasureRefused,
    live_questioner,
    record_result,
    recorded_baseline,
    remeasure_mapper,
)


def test_the_baseline_is_the_recorded_mapper_file():
    """One SHIPPED source: evals/mapper/recorded.json, which must still
    describe the live corpus (the drift lock — editing the corpus or the
    ranker fails here until `python -c "from engine.evals.mapper import
    write_recorded; write_recorded()"` re-derives the record CONSCIOUSLY).
    The release record under docs/releases/ is deny-listed from the
    public mirror, so it can never be the runtime source."""
    from engine.evals.mapper import RECORDED_PATH, evaluate_mapper_set

    committed = json.loads(RECORDED_PATH.read_text(encoding="utf-8"))
    assert committed == evaluate_mapper_set()
    assert recorded_baseline() == {"recall_at_5": committed["recall_at_5"],
                                   "false_gap_rate": committed["false_gap_rate"],
                                   "true_gap_recall": committed["true_gap_recall"]}
    assert recorded_baseline() == {"recall_at_5": 0.7368,
                                   "false_gap_rate": 0.0789,
                                   "true_gap_recall": 0.2917}


def test_empty_enrichment_reproduces_the_baseline_exactly(tmp_path):
    """questioner returning nothing = the committed corpus verbatim —
    the measured rates must equal the recorded baseline to the digit
    (determinism + the B75§4a unmoved claim, through the harness)."""
    result = remeasure_mapper(lambda card, body: [],
                              workspace=tmp_path / "ws")
    assert result["mode"] == "scripted"
    assert result["measured"] == recorded_baseline()
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
    assert set(result["delta"]) == set(recorded_baseline())
    for key in result["regressions"]:
        assert key in recorded_baseline()


def test_recording_a_scripted_run_is_refused(tmp_path):
    with pytest.raises(RemeasureRefused, match="wearing the model's"):
        remeasure_mapper(lambda c, b: [], workspace=tmp_path / "ws",
                         record=True, live=False)
    assert not (tmp_path / "result.json").exists()


def test_live_mode_refuses_without_the_flag(tmp_path, monkeypatch):
    """P2-37: live=True used to be a keyword the caller declared. Now the
    flag the live caller's constructor honours gates it too."""
    monkeypatch.delenv("RFP_LIVE", raising=False)
    with pytest.raises(RemeasureRefused, match="RFP_LIVE=1 is not set"):
        remeasure_mapper(lambda c, b: [], workspace=tmp_path / "ws",
                         live=True, record=True,
                         record_path=tmp_path / "result.json")
    assert not (tmp_path / "result.json").exists()


def test_live_mode_refuses_a_bare_callable(tmp_path, monkeypatch):
    """With the flag set, a lambda still cannot wear the live name —
    only live_questioner's product can, and that needs a traced
    LiveCaller (which refuses construction without credentials)."""
    monkeypatch.setenv("RFP_LIVE", "1")
    with pytest.raises(RemeasureRefused, match="bare callable"):
        remeasure_mapper(lambda c, b: [], workspace=tmp_path / "ws",
                         live=True, record=True,
                         record_path=tmp_path / "result.json")
    assert not (tmp_path / "result.json").exists()
    with pytest.raises(RemeasureRefused, match="TracedCaller wrapping a "
                                               "LiveCaller"):
        live_questioner(lambda c, b: [])


def test_the_live_door_opens_for_a_traced_live_caller(tmp_path, live_env):
    """The positive twin, zero spend: a real LiveCaller behind a stub
    client (the tests/llm fixture), traced, is what live_questioner
    accepts — and the recorded result names the live mode."""
    from engine.llm.caller import TracedCaller
    from engine.llm.config import model_prices
    from engine.llm.live import LiveCaller
    from engine.runlog import RunLogger
    from tests.llm.test_live_caller import StubClient, _response

    log = RunLogger(tmp_path / "ws", run_id="run_0001", pursuit_id="eval")
    stub = StubClient([_response("What is the scope?\nWho leads it?")] * 60)
    caller = TracedCaller(LiveCaller(client=stub, sleep=lambda s: None), log,
                          prices=model_prices()["prices"], ceiling_usd=100.0)
    questioner = live_questioner(caller)
    assert questioner.live is True
    result = remeasure_mapper(questioner, workspace=tmp_path / "ws",
                              live=True, record=True,
                              record_path=tmp_path / "result.json")
    assert result["mode"] == "live"
    assert result["enriched_cards"] > 0
    assert result["recorded"] is True
    written = json.loads((tmp_path / "result.json").read_text("utf-8"))
    assert written["mode"] == "live" and written["recorded"] is True


def test_recording_writes_what_a_live_run_hands_it(tmp_path):
    """The writer checks the mode it is handed rather than trusting the
    caller: a scripted result is refused at the write."""
    with pytest.raises(RemeasureRefused, match="only a live result"):
        record_result({"mode": "scripted"}, tmp_path / "r.json")
    out = record_result({"mode": "live", "measured": {}}, tmp_path / "r.json")
    assert out["recorded"] is True
    assert json.loads((tmp_path / "r.json").read_text("utf-8"))["recorded"]


@pytest.fixture
def live_env(monkeypatch):
    from tests.llm.test_live_caller import KEY
    monkeypatch.setenv("RFP_LIVE", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
