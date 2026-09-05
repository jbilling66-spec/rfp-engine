"""P2-35 + M-19 (P26b-3): the baseline lock, and the fingerprint re-pin
proven honest.

The four environment fingerprints sat in the same file as the measures,
so an edited recall cleared a blocking bar under commit review alone.
Now a sibling `baseline.lock.json` carries a digest of every
non-fingerprint field, written only by the live re-baseline arm and
read back by `check_baseline`. And `files_fingerprint` gained a frame
per file (M-19), which moved three committed digests without moving a
byte under them — the last test recomputes the LEGACY digest over
today's files and matches it to the 0.7.0 record.
"""

import hashlib
import json
from pathlib import Path

import pytest

from engine.evals.cases import (lock_path, measures_fingerprint, verify_lock,
                                write_lock, write_report)

ROOT = Path(__file__).resolve().parents[2]
AT = "2026-09-04T12:00:00Z"
RECORD_0_7_0 = ROOT / "docs" / "releases" / "0.7.0+8e7f7d3" / "eval-results.json"


def _live_report(cases):
    from engine.validation.poison import (cases_fingerprint, code_fingerprint,
                                          model_fingerprint,
                                          prompts_fingerprint)
    return {"suite": "poison_set", "at": AT, "n_cases": 60, "n_flagged": 30,
            "recall": 1.0, "precision": 1.0, "confusion": {},
            "misses": [], "run_id": "run_test",
            "prompts_fingerprint": prompts_fingerprint(),
            "cases_fingerprint": cases_fingerprint(cases),
            "model_fingerprint": model_fingerprint(),
            "code_fingerprint": code_fingerprint()}


@pytest.fixture(scope="module")
def cases():
    from engine.validation.poison import load_cases
    return load_cases()


def test_an_edited_recall_is_refused_by_name(tmp_path, cases):
    from engine.validation.poison import (BaselineMismatch, check_baseline,
                                          write_baseline)

    path = tmp_path / "baseline.json"
    write_baseline(_live_report(cases), path)
    write_lock(path, suite="poison_set", run_id="run_test", at=AT)
    assert check_baseline(path, cases=cases)["recall"] == 1.0

    # The edit the register described: a green number typed over a red
    # one, every environment fingerprint intact.
    edited = json.loads(path.read_text(encoding="utf-8"))
    edited["recall"] = 0.5
    write_report(edited, path)
    with pytest.raises(BaselineMismatch, match="no longer match their lock"):
        check_baseline(path, cases=cases)


def test_a_missing_lock_is_refused(tmp_path, cases):
    from engine.evals.claim_extraction import (BaselineMismatch,
                                               cases_fingerprint,
                                               check_baseline,
                                               code_fingerprint,
                                               model_fingerprint,
                                               prompts_fingerprint,
                                               write_baseline)
    from engine.evals.claim_extraction import load_cases as load_ce

    ce_cases = load_ce()
    path = tmp_path / "baseline.json"
    write_baseline({"claim_extraction_recall": 1.0,
                    "claim_over_extraction_rate": 0.0, "n_cases": 21,
                    "n_controls": 4, "at": AT,
                    "prompts_fingerprint": prompts_fingerprint(),
                    "cases_fingerprint": cases_fingerprint(ce_cases),
                    "model_fingerprint": model_fingerprint(),
                    "code_fingerprint": code_fingerprint()}, path)
    with pytest.raises(BaselineMismatch, match="no lock beside"):
        check_baseline(path, cases=ce_cases)
    assert not lock_path(path).exists()


def test_the_lock_ignores_the_environment_fingerprints(tmp_path, cases):
    """The four environment fingerprints are checked by their own
    guards; the lock covers everything ELSE, so a stale prompt digest
    reads as 'prompt changed' (its own message), never as a lock miss."""
    from engine.validation.poison import (BaselineMismatch, check_baseline,
                                          write_baseline)

    path = tmp_path / "baseline.json"
    report = _live_report(cases)
    write_baseline(report, path)
    write_lock(path, suite="poison_set", run_id="run_test", at=AT)
    assert measures_fingerprint(report) == measures_fingerprint(
        dict(report, prompts_fingerprint="0" * 64))
    write_baseline(dict(report, prompts_fingerprint="0" * 64), path)
    with pytest.raises(BaselineMismatch, match="prompts changed"):
        check_baseline(path, cases=cases)
    assert verify_lock(path, dict(report, prompts_fingerprint="0" * 64)) is None


def test_rebaseline_writes_the_lock_its_check_reads(tmp_path):
    """The arm is the one writer: it locks the file it just wrote, then
    its own guard re-read proves both together."""
    from tests.evals.test_rebaseline import (_flag_everything_script,
                                             _scripted_caller_factory)
    from engine.evals.rebaseline import rebaseline

    path = tmp_path / "baseline.json"
    result = rebaseline(
        "poison", make_caller=_scripted_caller_factory(_flag_everything_script()),
        workspace=tmp_path / "ws", at=AT, baseline_path=path)
    lock = json.loads(result["lock_path"].read_text(encoding="utf-8"))
    assert result["lock_path"] == lock_path(path)
    assert lock["locked_by"] == "rebaseline"
    assert lock["run_id"] == result["run_id"]
    assert lock["measures_fingerprint"] == measures_fingerprint(
        json.loads(path.read_text(encoding="utf-8")))


def test_committed_baselines_match_their_locks():
    """Both live baselines on disk pass their locks — and both locks
    name the run that produced the number they lock."""
    from engine.evals import claim_extraction
    from engine.validation import poison

    for module in (poison, claim_extraction):
        baseline = json.loads(module.BASELINE_PATH.read_text(encoding="utf-8"))
        assert verify_lock(module.BASELINE_PATH, baseline) is None, module
        lock = json.loads(lock_path(module.BASELINE_PATH).read_text(
            encoding="utf-8"))
        assert lock["run_id"] == baseline["run_id"]
        assert lock["at"] == baseline["at"]


def _legacy_files_fingerprint(*paths: Path) -> str:
    """files_fingerprint as it was before M-19: bytes concatenated with
    no frame — reproduced here, never kept in engine/."""
    digest = hashlib.sha256()
    for path in paths:
        digest.update(Path(path).read_bytes())
    return digest.hexdigest()


# The legacy digests as the 0.7.0 record carries them (docs/releases/
# 0.7.0+8e7f7d3/eval-results.json — private, deny-listed from the public
# mirror, so the test carries the citation and cross-checks it wherever
# the record exists).
LEGACY = {
    "claim_extraction": "522894ff88d3cd86a4185dc50b4e70a9e4740419739b03e516feb33f8e2f1bbe",
    "poison": "47d93f1c239c1a6f263b9c3482e0507122a26c564935faba70f8a6de542f9d3e",
    "voice": "6c790824cf4828922bc96e9550a0ac08cfca949833d813c2d117f85c28e803c5",
}


def test_the_re_pin_hashed_the_same_bytes():
    """M-19 moved three committed digests without a re-measure. The
    honest proof that nothing under them moved: the LEGACY digest over
    today's prompt and spec files equals what the 0.7.0 record carried
    (the literals above; verified against the record itself where the
    private repo has it)."""
    if RECORD_0_7_0.exists():
        record = json.loads(RECORD_0_7_0.read_text(encoding="utf-8"))["suites"]
        assert LEGACY == {
            "claim_extraction": record["claim_extraction"]["fingerprints"][
                "prompts_fingerprint"],
            "poison": record["poison"]["fingerprints"]["prompts_fingerprint"],
            "voice": record["voice"]["fingerprints"]["spec_fingerprint"]}
    prompts = ROOT / "prompts"
    assert _legacy_files_fingerprint(
        prompts / "claim_auditor" / "prompt.md") == LEGACY["claim_extraction"]
    assert _legacy_files_fingerprint(
        prompts / "claim_auditor" / "prompt.md",
        prompts / "claim_verifier" / "prompt.md") == LEGACY["poison"]
    assert _legacy_files_fingerprint(
        ROOT / "config" / "voice-spec.md") == LEGACY["voice"]
    # And the re-pinned digests are the new function over the same files.
    from engine.evals.claim_extraction import prompts_fingerprint as ce_fp
    from engine.evals.voice import spec_fingerprint
    from engine.validation.poison import prompts_fingerprint as po_fp
    for module_path, current in (
            (ROOT / "evals" / "claim-extraction" / "baseline.json", ce_fp()),
            (ROOT / "evals" / "poison" / "baseline.json", po_fp())):
        assert json.loads(module_path.read_text(encoding="utf-8"))[
            "prompts_fingerprint"] == current
    assert json.loads((ROOT / "evals" / "voice" / "recorded.json").read_text(
        encoding="utf-8"))["spec_fingerprint"] == spec_fingerprint()
