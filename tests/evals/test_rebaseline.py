"""The live re-baseline arm (cX, B40/D6). Every property below is proved
OFFLINE with an injected scripted caller — the arm's one live-only part
is LiveCaller construction, which carries its own refusal proofs
(tests/llm/test_live_refusals.py, B30(e)).

The point of testing the arm rather than only its refusal: a flag whose
sole tested behaviour is "no" is not the capability (refusal-is-not-
delivery). What is exercised here is the whole path — case load, suite
run, run-log discipline, baseline write, and the guard re-read that
proves the file just written can satisfy the check that stales it.
"""

import json

import pytest

from engine.cli.evals import register
from engine.contracts.validate import check_runlog_payloads, validate
from engine.evals import rebaseline as _rb
from engine.evals.rebaseline import RebaselineRefused, rebaseline
from engine.llm import FakeCaller, TracedCaller
from engine.runlog import assert_seq_gapless, read_run
from engine.validation import poison as _poison

AT = "2026-08-10T12:00:00"


def _parse(argv):
    import argparse
    parser = argparse.ArgumentParser()
    register(parser.add_subparsers(dest="cmd"))
    return parser.parse_args(argv)


def _flag_everything_script():
    """Derived from the prompt the auditor is actually given (the house
    derive-fake-from-prompt pattern): the script cannot drift from the
    prompt's own frame because it reads the prose back out of it."""
    def extractor(prompt):
        prose = prompt.split(
            "DRAFTED PROSE (extract claims from this text only):\n")[1].split(
            "\n\nFACT SHEET CATALOG")[0]
        return json.dumps({"claims": [{"slot_id": None, "text": prose,
                                       "tier": 1, "fact_sheet_ref": None}]})
    return {"claim_auditor": extractor,
            "claim_verifier": '{"verdict": "UNSUPPORTED", "reasons": ["r"]}'}


def _scripted_caller_factory(script):
    def make_caller(log):
        return TracedCaller(FakeCaller(script), log, ceiling_usd=100.0)
    return make_caller


# --- the refusals ---------------------------------------------------------

def test_rebaseline_without_live_is_refused_and_writes_nothing(capsys,
                                                               monkeypatch):
    """A scripted re-baseline would record the SCRIPT's recall under the
    model's name. The refusal has to come before anything is written."""
    calls = []
    monkeypatch.setattr(_rb, "rebaseline",
                        lambda *a, **k: calls.append(a) or {})
    args = _parse(["eval", "--rebaseline", "all"])
    assert args.fn(args) == 1
    out = capsys.readouterr().out
    assert "REFUSED" in out and "--live" in out
    assert not calls, "a suite ran despite the refusal"


def test_live_without_rebaseline_is_refused(capsys):
    args = _parse(["eval", "--live"])
    assert args.fn(args) == 1
    assert "REFUSED" in capsys.readouterr().out


def test_unknown_suite_is_refused_by_name():
    with pytest.raises(RebaselineRefused, match="unknown suite"):
        rebaseline("nonesuch", make_caller=lambda log: None, at=AT)


# --- the arm itself, driven end to end offline ----------------------------

def test_arm_runs_the_suite_writes_the_baseline_and_passes_its_own_guard(
        tmp_path):
    cases = _poison.load_cases()
    path = tmp_path / "baseline.json"
    result = rebaseline(
        "poison", make_caller=_scripted_caller_factory(_flag_everything_script()),
        workspace=tmp_path / "ws", at=AT, baseline_path=path,
        engine_version="0.1.0+test", out=lambda *a: None)

    # The report is the suite's own scoring, not the arm's arithmetic.
    assert result["report"]["recall"] == 1.0        # flag-everything...
    assert result["report"]["precision"] == 0.5     # ...over a 30/30 set

    # Written, and able to satisfy the guard that stales it — the loop
    # this arm exists to close.
    assert path.exists()
    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["recall"] == 1.0
    assert _poison.check_baseline(path, cases=cases)["recall"] == 1.0


def test_the_run_log_is_schema_valid_gapless_and_bench_moded(tmp_path):
    """Eval dollars must never enter a production series: the run these
    calls are logged under says regression_bench on its own header."""
    result = rebaseline(
        "claim_extraction",
        make_caller=_scripted_caller_factory(_flag_everything_script()),
        workspace=tmp_path / "ws", at=AT,
        baseline_path=tmp_path / "b.json", out=lambda *a: None)

    records = read_run(result["run_path"])
    assert_seq_gapless(records)
    for record in records:
        validate("run_log", record)
        check_runlog_payloads(record)
    header = records[0]
    assert header["record_type"] == "run_start"
    assert header["run"]["mode"] == "regression_bench"
    assert records[-1]["run"]["status"] == "completed"


def test_second_invocation_opens_a_fresh_run_id(tmp_path):
    """Two re-measures in one close step must not overwrite each other's
    trace — the run id is the only record of what the first one spent."""
    ws = tmp_path / "ws"
    make = _scripted_caller_factory(_flag_everything_script())
    first = rebaseline("claim_extraction", make_caller=make, workspace=ws, at=AT,
                       baseline_path=tmp_path / "b1.json", out=lambda *a: None)
    second = rebaseline("claim_extraction", make_caller=make, workspace=ws, at=AT,
                        baseline_path=tmp_path / "b2.json", out=lambda *a: None)
    assert first["run_id"] == "run_0001" and second["run_id"] == "run_0002"
    assert first["run_path"] != second["run_path"]
    assert first["run_path"].exists() and second["run_path"].exists()


def test_a_rebaseline_preserves_the_number_it_replaces(tmp_path):
    """P11-C5. `rebaseline()` overwrites unconditionally, so before this
    the replaced number was simply gone.

    That matters because extraction recall has already MOVED between two
    runs of the same system (0.8235 -> 0.7059). A series of one point
    cannot separate a regression from variance, which is the question the
    next measurement exists to answer — and reconstructing the prior
    number from git history is not a series, it is an archaeology project.
    """
    ws = tmp_path / "ws"
    path = tmp_path / "baseline.json"
    make = _scripted_caller_factory(_flag_everything_script())

    first = rebaseline("claim_extraction", make_caller=make, workspace=ws,
                       at=AT, baseline_path=path, out=lambda *a: None)
    hist = _rb.history_path(path)
    assert not hist.exists(), \
        "a first baseline replaces nothing, so it records nothing"

    second = rebaseline("claim_extraction", make_caller=make, workspace=ws,
                        at="2026-08-12T00:00:00", baseline_path=path,
                        out=lambda *a: None)

    lines = [json.loads(x) for x in hist.read_text().splitlines()]
    assert len(lines) == 1, "one overwrite, one history line"
    kept = lines[0]
    # The line describes the REPLACED run, not the one that just ran.
    assert kept["at"] == first["report"]["at"] != second["report"]["at"]
    assert kept["headline"]["claim_extraction_recall"] == \
        first["report"]["claim_extraction_recall"]
    for key in ("prompts_fingerprint", "cases_fingerprint",
                "model_fingerprint", "code_fingerprint"):
        assert kept[key] == first["report"][key], \
            "a history line without its fingerprints cannot be compared to"
    # ...including the FOURTH lock: C5 archived the triad and was never
    # revisited when C7 added code_fingerprint, so the archived number
    # could not prove which scorer produced it (B49/F-2).
    # And the attribution is the run that PRODUCED the number — stamping
    # the replacing run's id onto it would be worse than no provenance.
    assert kept["run_id"] == first["run_id"] != second["run_id"]


def test_every_history_line_carries_provenance(tmp_path):
    """The B43a shape, structurally excluded going forward: the committed
    histories gained a line at C8 with the same numbers and clock as the
    seed above it and NO source or run_id — two identical observations
    readable as a property (B49/F-3, recorded not rewritten). Every line
    this seam writes now says where its number came from: the producing
    run's id when the baseline recorded one, else an explicit label."""
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps(
        {"at": "2026-08-11T03:05:33Z", "suite": "claim_extraction_set",
         "claim_extraction_recall": 0.7059, "claim_over_extraction_rate": 0.0,
         "prompts_fingerprint": "p", "cases_fingerprint": "c",
         "model_fingerprint": "m", "code_fingerprint": "k"}))
    # No run_id in the baseline, no source given: the line must label
    # itself rather than sit unattributable in the series.
    _rb.append_history(path, spec=_rb.SUITES["claim_extraction"])
    line = json.loads(_rb.history_path(path).read_text().strip())
    assert "predates run_id recording" in line["source"]
    assert line["code_fingerprint"] == "k", \
        "every lock the baseline carried travels to the archive"

    # A baseline that knows its producing run passes that id through —
    # never the id of whatever run happens to be replacing it.
    path.write_text(json.dumps(
        {"at": "2026-08-11T22:16:10Z", "suite": "claim_extraction_set",
         "claim_extraction_recall": 0.8824, "claim_over_extraction_rate": 0.0,
         "run_id": "run_0006", "prompts_fingerprint": "p",
         "cases_fingerprint": "c", "model_fingerprint": "m",
         "code_fingerprint": "k"}))
    _rb.append_history(path, spec=_rb.SUITES["claim_extraction"],
                       run_id="run_9999")
    last = [json.loads(x) for x in
            _rb.history_path(path).read_text().splitlines()][-1]
    assert last["run_id"] == "run_0006", \
        "the archive must credit the run that produced the number"


def test_a_crashed_rebaseline_leaves_history_untouched(tmp_path, monkeypatch):
    """The baseline still stands after a crash, so history must not claim
    it was replaced — otherwise the series gains a point for a measurement
    that never landed."""
    ws = tmp_path / "ws"
    path = tmp_path / "baseline.json"
    make = _scripted_caller_factory(_flag_everything_script())
    rebaseline("claim_extraction", make_caller=make, workspace=ws, at=AT,
               baseline_path=path, out=lambda *a: None)
    before = path.read_text()

    def _boom(*a, **k):
        raise RuntimeError("model died mid-suite")

    monkeypatch.setattr(_rb.SUITES["claim_extraction"]["module"],
                        "run_extraction_suite", _boom)
    with pytest.raises(RuntimeError, match="mid-suite"):
        rebaseline("claim_extraction", make_caller=make, workspace=ws, at=AT,
                   baseline_path=path, out=lambda *a: None)

    assert path.read_text() == before, "the standing baseline was touched"
    assert not _rb.history_path(path).exists(), \
        "history gained a line for a replacement that never happened"


def test_a_transcribed_history_line_says_so(tmp_path):
    """Provenance, never dressed up as a measurement: seeding history from
    an existing baseline records a number nobody observed in that act, and
    the line has to admit it (the B33(1) discipline applied to records)."""
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps(
        {"at": "2026-08-11T03:05:33Z", "suite": "claim_extraction_set",
         "claim_extraction_recall": 0.7059, "claim_over_extraction_rate": 0.0,
         "prompts_fingerprint": "p", "cases_fingerprint": "c",
         "model_fingerprint": "m"}))
    _rb.append_history(path, spec=_rb.SUITES["claim_extraction"],
                       source="transcribed from baseline.json at b86d50a")
    line = json.loads(_rb.history_path(path).read_text().strip())
    assert line["source"] == "transcribed from baseline.json at b86d50a"
    assert line["headline"]["claim_extraction_recall"] == 0.7059


def test_the_committed_history_seed_is_marked_as_transcribed():
    """The COMMITTED seed lines, not a fixture. Line 1 of each real history
    was lifted from the standing baseline rather than measured, and a
    reader six months out must not mistake it for a third data point."""
    for spec in _rb.SUITES.values():
        hist = _rb.history_path(spec["module"].BASELINE_PATH)
        assert hist.exists(), f"{hist} — the seed is part of the record"
        lines = [json.loads(x) for x in hist.read_text().splitlines() if x]
        assert lines, f"{hist} is empty"
        assert "transcribed" in lines[0]["source"], (
            "the seed line must declare that it was copied, not observed")
        # It still has to be comparable, or it is decoration.
        assert all(lines[0][k] for k in ("prompts_fingerprint",
                                         "cases_fingerprint",
                                         "model_fingerprint"))
        assert any(v is not None for v in lines[0]["headline"].values())


def test_a_baseline_that_fails_its_own_guard_is_deleted(tmp_path,
                                                        monkeypatch):
    """If the guard cannot accept what we just wrote, something moved
    mid-run — and a stale baseline left on disk is worse than none: it is
    exactly the state the re-measure was run to clear."""
    path = tmp_path / "baseline.json"
    monkeypatch.setattr(_poison, "check_baseline", _raise_mismatch)
    with pytest.raises(RebaselineRefused, match="own guard"):
        rebaseline("poison",
                   make_caller=_scripted_caller_factory(
                       _flag_everything_script()),
                   workspace=tmp_path / "ws", at=AT, baseline_path=path,
                   out=lambda *a: None)
    assert not path.exists(), "a baseline failing its guard survived"


def _raise_mismatch(*args, **kwargs):
    raise _poison.BaselineMismatch("planted: the corpus moved")


def test_a_crashed_suite_still_closes_its_run_log_as_failed(tmp_path,
                                                            monkeypatch):
    """A partial live run still spent money; the trace of what it spent is
    what makes the next attempt honest (P8's crashed attempt 1)."""
    def explode(*args, **kwargs):
        raise RuntimeError("planted: the wire came back malformed")

    monkeypatch.setattr(_poison, "run_poison_suite", explode)
    ws = tmp_path / "ws"
    with pytest.raises(RuntimeError, match="planted"):
        rebaseline("poison", make_caller=_scripted_caller_factory({}),
                   workspace=ws, at=AT, baseline_path=tmp_path / "b.json",
                   out=lambda *a: None)
    records = read_run(ws / "runs" / "run_0001" / "run.jsonl")
    assert records[-1]["record_type"] == "run_end"
    assert records[-1]["run"]["status"] == "failed"
    assert not (tmp_path / "b.json").exists()
