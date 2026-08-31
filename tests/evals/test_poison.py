"""The poison set + harness (B34(16,17)). Offline this proves the METRIC
MATH (planted flag-everything and approve-everything scripts), the case
discipline, the anti-memorization sweep, and the dual-fingerprint
refusals — the real recall/precision numbers are first measured live at
the C15 milestone (B33(1)) and recorded in evals/poison/baseline.json."""

import json

import pytest

from engine.kb import KBStore
from engine.llm import FakeCaller, TracedCaller
from engine.runlog import RunLogger
from engine.validation.poison import (
    BaselineMismatch,
    CASES_PATH,
    ROOT,
    cases_fingerprint,
    check_baseline,
    model_fingerprint,
    load_cases,
    prompts_fingerprint,
    run_poison_suite,
    write_baseline,
)

AT = "2026-08-08T12:00:00"

TRUTH_BY_PREFIX = {
    "sup": "true", "ctl": "true", "t2": "true",
    "stl": "stale", "sil": "unverifiable",
    "gen": "fabricated", "plu": "fabricated", "inf": "fabricated",
    "mis": "fabricated", "par": "fabricated", "tmp": "fabricated",
    "cmp": "fabricated", "att": "fabricated", "cam": "fabricated",
}


@pytest.fixture(scope="module")
def cases():
    return load_cases()


def test_sixty_cases_thirty_thirty_and_held_out(cases):
    assert len(cases) == 60
    true_half = [c for c in cases if c["expected"]["claim_truth"] == "true"]
    assert len(true_half) == 30
    held = sum(1 for c in cases if c["held_out"])
    assert held / len(cases) >= 0.2


def test_scoring_wiring_per_truth(cases):
    for case in cases:
        flagged = case["expected"]["must_flag"]
        scoring = case["scoring"]
        if flagged:
            assert scoring["metric"] == "tier1_recall"
            assert scoring["bar"] == 0.98 and scoring["blocking"] is True
            assert case["expected"]["claim_truth"] != "true"
        else:
            assert scoring["metric"] == "tier1_precision"
            assert scoring["bar"] == 0.85 and scoring["blocking"] is False
            assert case["expected"]["claim_truth"] == "true"


def test_category_prefix_agrees_with_expected_bucket(cases):
    # v1 shipped a case filed under the wrong category, silently corrupting
    # per-category regression rows — the prefix IS the category here.
    for case in cases:
        prefix = case["case_id"].removeprefix("poison_").split("_")[0]
        assert prefix in TRUTH_BY_PREFIX, f"unknown category {prefix}"
        assert case["expected"]["claim_truth"] == TRUTH_BY_PREFIX[prefix], \
            f"{case['case_id']} filed under the wrong bucket"


def test_tier_camouflage_cases_are_tier1_labeled(cases):
    cams = [c for c in cases if c["case_id"].startswith("poison_cam_")]
    assert cams and all(c["expected"]["claim_tier"] == 1 for c in cams)


def test_anti_memorization_no_case_text_in_the_prompts(cases):
    # Both directions of B34(16): the prompts must not quote the poison
    # set. The sweep is non-vacuous by construction: 60 planted texts.
    def normalize(text):
        return " ".join(text.lower().split())

    prompts = normalize(
        (ROOT / "prompts" / "claim_auditor" / "prompt.md").read_text()
        + (ROOT / "prompts" / "claim_verifier" / "prompt.md").read_text())
    for case in cases:
        claim = normalize(case["input"]["prompt_context"])
        assert claim not in prompts, \
            f"{case['case_id']}: claim text appears in a prompt file — " \
            f"recall would measure memorization"


def _suite_run(tmp_path, cases, script):
    store = KBStore(ROOT / "kb")
    log = RunLogger(tmp_path / "poison", run_id="run_0001", pursuit_id="eval")
    log.run_start(mode="regression_bench", engine_version="0.1.0",
                  config={"suite": "poison"}, kb_snapshot=store.snapshot())
    caller = TracedCaller(FakeCaller(script), log, ceiling_usd=100.0)
    report = run_poison_suite(store, caller, cases, at=AT)
    log.run_end(status="completed")
    return report, log


def test_metric_math_flag_everything(tmp_path, cases):
    first_fact = "kb_fact000001"

    def extractor(prompt):
        prose = prompt.split(
            "DRAFTED PROSE (extract claims from this text only):\n")[1].split(
            "\n\nFACT SHEET CATALOG")[0]
        return json.dumps({"claims": [{"slot_id": None, "text": prose,
                                       "tier": 1,
                                       "fact_sheet_ref": first_fact}]})

    script = {"claim_auditor": extractor,
              "claim_verifier": '{"verdict": "UNSUPPORTED", "reasons": ["r"]}'}
    report, log = _suite_run(tmp_path, cases, script)
    assert report["recall"] == 1.0        # every bad case caught...
    assert report["precision"] == 0.5     # ...by flagging everything (30/60)
    assert report["n_flagged"] == 60
    assert sum(b["total"] for b in report["confusion"].values()) == 60


def test_metric_math_approve_everything(tmp_path, cases):
    def extractor(prompt):
        prose = prompt.split(
            "DRAFTED PROSE (extract claims from this text only):\n")[1].split(
            "\n\nFACT SHEET CATALOG")[0]
        return json.dumps({"claims": [{"slot_id": None, "text": prose,
                                       "tier": 2, "fact_sheet_ref": None}]})

    report, log = _suite_run(tmp_path, cases, {"claim_auditor": extractor})
    assert report["recall"] == 0.0        # nothing audited = nothing caught
    assert report["n_flagged"] == 0       # precision is vacuous at 1.0 —
    assert report["precision"] == 1.0     # n_flagged says so honestly


def test_baseline_quadruple_fingerprint_refusals(tmp_path, cases):
    from engine.validation.poison import code_fingerprint

    report = {"suite": "poison_set", "at": AT, "n_cases": 60, "n_flagged": 1,
              "recall": 0.5, "precision": 0.5, "confusion": {},
              "prompts_fingerprint": prompts_fingerprint(),
              "cases_fingerprint": cases_fingerprint(cases),
              "model_fingerprint": model_fingerprint(),
              "code_fingerprint": code_fingerprint()}
    path = tmp_path / "baseline.json"
    write_baseline(report, path)
    assert check_baseline(path, cases=cases)["recall"] == 0.5

    # Stale cases fingerprint: the corpus moved under the guard.
    with pytest.raises(BaselineMismatch, match="cases changed"):
        check_baseline(path, cases=cases[:-1])

    # A baseline with no fingerprints cannot prove what it measured.
    stripped = {k: v for k, v in report.items()
                if k != "prompts_fingerprint"}
    write_baseline(stripped, path)
    with pytest.raises(BaselineMismatch, match="lacks prompts_fingerprint"):
        check_baseline(path, cases=cases)

    # Stale prompts fingerprint: a prompt tweak costs a live re-baseline.
    write_baseline(dict(report, prompts_fingerprint="0" * 64), path)
    with pytest.raises(BaselineMismatch, match="prompts changed"):
        check_baseline(path, cases=cases)

    # Stale MODEL fingerprint (P10-F14): same prompts, same cases, a
    # different model pin or temperature. The pair could not see this,
    # which is how an unpinned temperature stayed invisible for ten
    # phases — a recorded number describing a system that had moved.
    write_baseline(dict(report, model_fingerprint="0" * 64), path)
    with pytest.raises(BaselineMismatch, match="sampling parameters"):
        check_baseline(path, cases=cases)

    # Stale CODE fingerprint (P11-C7): same prompts, same cases, same
    # model — a different parser or scorer. The other three are all data
    # and none of them can see engine/ change underneath the number.
    write_baseline(dict(report, code_fingerprint="0" * 64), path)
    with pytest.raises(BaselineMismatch, match="SCORING CODE"):
        check_baseline(path, cases=cases)

    with pytest.raises(BaselineMismatch, match="not been measured"):
        check_baseline(tmp_path / "absent.json", cases=cases)


def test_committed_baseline_if_present_is_current(cases):
    # Before the milestone: no baseline, and that absence is honest. After
    # C15 commits one, this test enforces the fingerprint lock forever.
    from engine.validation.poison import BASELINE_PATH
    if BASELINE_PATH.exists():
        baseline = check_baseline(cases=cases)
        assert {"recall", "precision", "at"} <= set(baseline)
    else:
        with pytest.raises(BaselineMismatch):
            check_baseline(cases=cases)


def _tier1_verbatim(prompt):
    prose = prompt.split(
        "DRAFTED PROSE (extract claims from this text only):\n")[1].split(
        "\n\nFACT SHEET CATALOG")[0]
    return json.dumps({"claims": [{"slot_id": None, "text": prose, "tier": 1,
                                   "fact_sheet_ref": "kb_fact000001"}]})


def _tier2_verbatim(prompt):
    prose = prompt.split(
        "DRAFTED PROSE (extract claims from this text only):\n")[1].split(
        "\n\nFACT SHEET CATALOG")[0]
    return json.dumps({"claims": [{"slot_id": None, "text": prose, "tier": 2,
                                   "fact_sheet_ref": None}]})


def _paraphrased(prompt):
    return json.dumps({"claims": [
        {"slot_id": None, "text": "wording that appears nowhere in the prose",
         "tier": 1, "fact_sheet_ref": "kb_fact000001"}]})


def _silent(prompt):
    return json.dumps({"claims": []})


def test_a_miss_names_which_subsystem_lost_the_claim(tmp_path, cases):
    """P10-F16 applied to the poison set. Recall alone cannot say whether a
    miss was the extractor staying silent, the tier boundary, the verbatim
    guard discarding a CORRECT extraction, or the verifier clearing a claim
    that reached it. Those are four bugs in four different places, and P8's
    F7 conclusion ('the auditor never extracted it') was drawn from a
    number that could not distinguish the first three.

    All four scripts below score recall 0.0. Only `causes` separates them —
    which is the whole point."""
    scripts = {
        "not_extracted": {"claim_auditor": _silent},
        "dropped_verbatim": {"claim_auditor": _paraphrased},
        "tiered_down": {"claim_auditor": _tier2_verbatim},
        "verifier_cleared": {
            "claim_auditor": _tier1_verbatim,
            "claim_verifier": '{"verdict": "SUPPORTED", "reasons": ["ok"]}'},
    }
    seen = {}
    for expected, script in scripts.items():
        report, _log = _suite_run(tmp_path / expected, cases, script)
        assert report["recall"] == 0.0, \
            f"{expected}: the scripts must be indistinguishable by recall"
        assert set(report["causes"]) == {expected}, \
            f"{expected}: got {report['causes']}"
        seen[expected] = report["causes"]

        # B46: a warning the taxonomy cannot name falls through to
        # `not_extracted` and blames the model for a row it produced. An
        # empty list here is the invariant, in every branch.
        assert all(d["unmarked_warnings"] == []
                   for d in report["miss_detail"].values()), \
            f"{expected}: parser emitted an unnameable warning"

    # Non-vacuity: four identical recall numbers, four distinct diagnoses.
    assert len({tuple(v) for v in seen.values()}) == 4


def test_miss_detail_quotes_the_guard_drop_rather_than_only_labelling_it(
        tmp_path, cases):
    report, _log = _suite_run(tmp_path, cases,
                              {"claim_auditor": _paraphrased})
    sample = report["miss_detail"][report["misses"][0]]
    assert sample["cause"] == "dropped_verbatim"
    assert any("not present in delivered prose" in w
               for w in sample["warnings"])
    assert sample["category"] in TRUTH_BY_PREFIX
