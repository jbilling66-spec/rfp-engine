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


def _real_digest():
    """P29a (P2-54): live_measure re-reads the model configuration's
    digest, so a fresh-looking record carries today's."""
    from engine.llm import effective_config
    from engine.runlog import config_digest
    return config_digest(effective_config())


def _live_looking(n_cases=44):
    return AnonymizationResult(ok=True, failures=[], n_cases=n_cases,
                               n_blocked=3, blocked=["anon_026"], mode="live")


def test_the_lane_reads_a_fresh_record_and_names_a_stale_or_absent_one(tmp_path):
    record = tmp_path / "live-record.json"
    absent = live_measure(CASES_PATH, record)
    assert absent["status"] == "not_measured" and "no live record" in absent["since"]

    path = record_live_result(_live_looking(), cases_path=CASES_PATH,
                              at="2026-09-05T00:00:00Z", workspace="w",
                              config_digest=_real_digest(), path=record)
    fresh = live_measure(CASES_PATH, path)
    assert fresh == {"status": "measured", "at": "2026-09-05T00:00:00Z",
                     "n_cases": 44, "n_blocked": 3, "failures": [],
                     "pass": True}

    # the corpus moves: one needle added to one case → the record is stale
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    cases[0]["expected"]["must_not_contain"].append("Robotics")
    moved = tmp_path / "cases.json"
    moved.write_text(json.dumps(cases), encoding="utf-8")
    assert cases_fingerprint(moved) != cases_fingerprint(CASES_PATH)
    stale = live_measure(moved, path)
    assert stale["status"] == "not_measured"
    # P29a (P2-54): the reason names the inputs that moved (the moved
    # case list sits beside no documents, so both parts differ)
    assert "cases, docs changed since the recorded run of 2026-09-05" in stale["since"]


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
    assert lane["measures"]["n_cases"] == 44
    assert "B35" not in lane["detail"]


def test_the_cli_live_flavor_refuses_without_the_flag(capsys, monkeypatch):
    monkeypatch.delenv("RFP_LIVE", raising=False)
    assert main(["eval", "--suite", "anonymization", "--live"]) == 1
    out = capsys.readouterr().out
    assert "anonymization --live refused" in out and "RFP_LIVE=1" in out
    assert not Path(CASES_PATH.parent / "live-record.json").exists()


# -- P29a: the record measures the readers under test ----------------------

def _one_case_corpus(tmp_path, case_id="anon_001"):
    """A one-case copy of the corpus with the floor lifted for the unit."""
    import shutil
    corpus = tmp_path / "anonymization"
    (corpus / "docs").mkdir(parents=True)
    cases = [c for c in json.loads(CASES_PATH.read_text(encoding="utf-8"))
             if c["case_id"] == case_id]
    shutil.copy(CASES_PATH.parent / "docs" / f"{case_id}.md",
                corpus / "docs" / f"{case_id}.md")
    (corpus / "cases.json").write_text(json.dumps(cases), encoding="utf-8")
    return corpus / "cases.json"


def test_a_rerun_into_one_workdir_measures_the_new_readers(tmp_path,
                                                          monkeypatch):
    """P1-50 (the audit's recipe): a clean run passes; its card is then
    salted with a synthetic third-party name; the SAME clean readers into
    the SAME workdir must pass again — they used to dedupe against the
    salted leftover, and the record condemned a reader that never wrote
    that text (or, the other way round, vouched for one that regressed)."""
    import engine.kb.evalset as evalset
    from engine.kb.evalset import run_anonymization_set
    cases_path = _one_case_corpus(tmp_path)
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    cases[0]["expected"]["must_not_contain"].append("Halvorsen")
    cases_path.write_text(json.dumps(cases), encoding="utf-8")
    monkeypatch.setitem(evalset.MINIMUM_N, "cases", 1)
    workdir = tmp_path / "work"
    first = run_anonymization_set(cases_path, workdir)
    assert first.ok is True, first.failures
    cards = list((workdir / "anon_001" / "kb" / "cards").glob("*.md"))
    assert cards, "run 1 wrote a card"
    for card in cards:
        card.write_text(card.read_text(encoding="utf-8")
                        + "\nHalvorsen Data Systems handled the extracts.\n",
                        encoding="utf-8")
    second = run_anonymization_set(cases_path, workdir)
    assert second.ok is True, second.failures
    assert not any("Halvorsen" in c.read_text(encoding="utf-8")
                   for c in (workdir / "anon_001" / "kb" / "cards").glob("*.md"))


def test_the_record_names_the_input_that_moved(tmp_path, monkeypatch):
    """P2-54: gate code, reader prompts, model pins and the model
    configuration each stale the record BY NAME; the case list and the
    documents still do."""
    import engine.kb.evalset as evalset
    record = tmp_path / "live-record.json"
    from engine.llm import effective_config
    from engine.runlog import config_digest
    record_live_result(_live_looking(), cases_path=CASES_PATH,
                       at="2026-09-10T00:00:00Z", workspace="ws",
                       config_digest=config_digest(effective_config()),
                       path=record)
    assert live_measure(CASES_PATH, record)["status"] == "measured"
    monkeypatch.setattr(evalset, "_gate_code_fingerprint", lambda: "moved")
    stale = live_measure(CASES_PATH, record)
    assert stale["status"] == "not_measured" and "gate code changed" in stale["since"]
    monkeypatch.undo()
    monkeypatch.setattr(evalset, "_reader_prompts_fingerprint", lambda: "moved")
    assert "reader prompts changed" in live_measure(CASES_PATH, record)["since"]
    monkeypatch.undo()
    written = json.loads(record.read_text(encoding="utf-8"))
    assert set(written["inputs"]) == {"cases", "docs", "gate code",
                                      "reader prompts", "model pins"}
    written["config_digest"] = "0" * 64
    record.write_text(json.dumps(written), encoding="utf-8")
    zeroed = live_measure(CASES_PATH, record)
    assert zeroed["status"] == "not_measured"
    assert "model configuration changed" in zeroed["since"]


def test_a_torn_record_reads_as_not_measured_not_a_crash(tmp_path):
    """P3-18: written atomically; an unreadable record is a reason."""
    record = tmp_path / "live-record.json"
    record.write_text('{"at": "2026-09-10T00:00:00Z", "n_cas', encoding="utf-8")
    torn = live_measure(CASES_PATH, record)
    assert torn["status"] == "not_measured"
    assert "unreadable" in torn["since"] and "JSONDecodeError" in torn["since"]
    record.write_bytes(b"")
    assert live_measure(CASES_PATH, record)["status"] == "not_measured"
