"""P28 (P1-4): the anonymization live arm cannot call itself live, a
scripted result is never recorded, and the release record reads the
recorded live measure only while the corpus it measured is today's.
"""

import json
from pathlib import Path

import pytest

from engine.cli.main import main
from engine.kb.evalset import (CASES_PATH, AnonymizationLiveRefused,
                               AnonymizationResult, cases_fingerprint,
                               live_caller_factory, live_measure,
                               record_live_result, run_anonymization_set)
from engine.llm import FakeCaller, SpendBudget, TracedCaller


def test_live_mode_refuses_without_the_flag(tmp_path, monkeypatch):
    monkeypatch.delenv("RFP_LIVE", raising=False)
    with pytest.raises(AnonymizationLiveRefused, match="RFP_LIVE=1 is not set"):
        run_anonymization_set(CASES_PATH, tmp_path, live=True,
                              caller_factory=lambda log: None)


def test_live_mode_refuses_a_bare_factory_even_with_the_flag(tmp_path,
                                                            monkeypatch):
    monkeypatch.setenv("RFP_LIVE", "1")
    factory = lambda log: TracedCaller(FakeCaller({}), log)  # noqa: E731
    with pytest.raises(AnonymizationLiveRefused,
                       match="not built by live_caller_factory"):
        run_anonymization_set(CASES_PATH, tmp_path, live=True,
                              caller_factory=factory)


def test_live_caller_factory_refuses_a_scripted_caller():
    with pytest.raises(AnonymizationLiveRefused, match="needs a LiveCaller"):
        live_caller_factory(FakeCaller({}), prices={}, budget=SpendBudget())


def test_a_scripted_result_is_never_recorded(tmp_path):
    result = run_anonymization_set(CASES_PATH, tmp_path)
    assert result.ok and result.mode == "scripted"
    with pytest.raises(AnonymizationLiveRefused, match="scripted"):
        record_live_result(result, cases_path=CASES_PATH, at="x",
                           workspace="w", config_digest="d",
                           path=tmp_path / "live-record.json")
    assert not (tmp_path / "live-record.json").exists()


def _live_looking(n_cases=42):
    return AnonymizationResult(ok=True, failures=[], n_cases=n_cases,
                               n_blocked=3, blocked=["anon_026"], mode="live")


def test_the_lane_reads_a_fresh_record_and_names_a_stale_or_absent_one(tmp_path):
    record = tmp_path / "live-record.json"
    absent = live_measure(CASES_PATH, record)
    assert absent["status"] == "not_measured" and "no live record" in absent["since"]

    path = record_live_result(_live_looking(), cases_path=CASES_PATH,
                              at="2026-09-05T00:00:00Z", workspace="w",
                              config_digest="d", path=record)
    fresh = live_measure(CASES_PATH, path)
    assert fresh == {"status": "measured", "at": "2026-09-05T00:00:00Z",
                     "n_cases": 42, "n_blocked": 3, "failures": [],
                     "pass": True}

    # the corpus moves: one needle added to one case → the record is stale
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    cases[0]["expected"]["must_not_contain"].append("Robotics")
    moved = tmp_path / "cases.json"
    moved.write_text(json.dumps(cases), encoding="utf-8")
    assert cases_fingerprint(moved) != cases_fingerprint(CASES_PATH)
    stale = live_measure(moved, path)
    assert stale["status"] == "not_measured"
    assert "corpus changed since the recorded run of 2026-09-05" in stale["since"]


def test_the_fingerprint_covers_the_documents_too(tmp_path):
    """A doc edit with the case list unchanged must stale the record."""
    import shutil
    copy = tmp_path / "anonymization"
    shutil.copytree(CASES_PATH.parent, copy)
    before = cases_fingerprint(copy / "cases.json")
    doc = copy / "docs" / "anon_001.md"
    doc.write_text(doc.read_text(encoding="utf-8") + "\nOne more line.\n",
                   encoding="utf-8")
    assert cases_fingerprint(copy / "cases.json") != before


def test_the_release_lane_carries_the_live_measure():
    from engine.evals.run import anonymization_lane
    lane = anonymization_lane()
    assert lane["measures"]["live"]["status"] in ("measured", "not_measured")
    assert lane["measures"]["n_cases"] == 42
    assert "B35" not in lane["detail"]


def test_the_cli_live_flavor_refuses_without_the_flag(capsys, monkeypatch):
    monkeypatch.delenv("RFP_LIVE", raising=False)
    assert main(["eval", "--suite", "anonymization", "--live"]) == 1
    out = capsys.readouterr().out
    assert "anonymization --live refused" in out and "RFP_LIVE=1" in out
    assert not Path(CASES_PATH.parent / "live-record.json").exists()
