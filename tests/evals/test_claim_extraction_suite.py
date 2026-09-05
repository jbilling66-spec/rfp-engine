"""The extraction-recall suite (F6, c11).

The model half cannot be honestly measured offline — a scripted extractor
reports its script's recall (B33(1)) — so what IS proven here is the
harness: that the metric math is right, that the suite can fail, that the
baseline refuses a stale comparison, and that the lane says
not_measured_live rather than inventing a number. The real recall arrives
at the owner-gated close step.
"""

import json

import pytest
from engine.evals.cases import write_lock
from engine.evals.claim_extraction import (BaselineMismatch, CASES_PATH,
                                     cases_fingerprint, check_baseline,
                                     load_cases, prompts_fingerprint,
                                     run_extraction_suite, write_baseline)
from engine.kb.store import KBStore
from engine.llm import FakeCaller, TracedCaller
from engine.runlog import RunLogger
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AT = "2026-08-10T12:00:00Z"


@pytest.fixture(scope="module")
def cases():
    return load_cases()


def _suite_run(tmp_path, cases, script):
    store = KBStore(ROOT / "kb")
    log = RunLogger(tmp_path / "extract", run_id="run_0001", pursuit_id="eval")
    log.run_start(mode="regression_bench", engine_version="0.1.0",
                  config={"suite": "extraction"}, kb_snapshot=store.snapshot())
    caller = TracedCaller(FakeCaller(script), log, ceiling_usd=100.0)
    report = run_extraction_suite(store, caller, cases, at=AT)
    log.run_end(status="completed")
    return report


def _extract_everything(prompt):
    prose = prompt.split(
        "DRAFTED PROSE (extract claims from this text only):\n")[1].split(
        "\n\nFACT SHEET CATALOG")[0]
    return json.dumps({"claims": [{"slot_id": None, "text": prose,
                                   "tier": 1,
                                   "fact_sheet_ref": "kb_fact000001"}]})


def _extract_nothing(prompt):
    return json.dumps({"claims": []})


def test_case_set_covers_every_recorded_p8_miss_mode(cases):
    """Fixture integrity: F6 exists because of three named failure modes
    from the live milestone. A suite missing one of them would leave the
    gap it was built to close unmeasured."""
    modes = {c["case_id"].removeprefix("extract_").rsplit("_", 1)[0]
             for c in cases}
    assert {"attribution", "quantifier", "inference"} <= modes
    controls = [c for c in cases if not c["expected"]["must_flag"]]
    assert len(controls) >= 4, "over-extraction needs its own controls"
    held = sum(1 for c in cases if c["held_out"])
    assert held / len(cases) >= 0.20


def test_metric_math_extract_everything(tmp_path, cases):
    """Flag-everything: recall is perfect and over-extraction is total —
    the pair is what stops a lazy extractor scoring well."""
    report = _suite_run(tmp_path, cases,
                        {"claim_auditor": _extract_everything,
                         "claim_verifier":
                             '{"verdict": "UNSUPPORTED", "reasons": ["r"]}'})
    assert report["claim_extraction_recall"] == 1.0
    assert report["claim_over_extraction_rate"] == 1.0
    assert report["over_extracted"] == sorted(
        c["case_id"] for c in cases if not c["expected"]["must_flag"])


def test_metric_math_extract_nothing(tmp_path, cases):
    """Extract-nothing: recall 0.0 and NO over-extraction. This is the
    exact P8 failure shape — a claim that never arrives cannot be
    flagged, and the poison set's single number could not see it."""
    report = _suite_run(tmp_path, cases, {"claim_auditor": _extract_nothing})
    assert report["claim_extraction_recall"] == 0.0
    assert report["claim_over_extraction_rate"] == 0.0
    assert len(report["misses"]) == sum(
        1 for c in cases if c["expected"]["must_flag"])


def _extract_as_tier_two(prompt):
    prose = prompt.split(
        "DRAFTED PROSE (extract claims from this text only):\n")[1].split(
        "\n\nFACT SHEET CATALOG")[0]
    return json.dumps({"claims": [{"slot_id": None, "text": prose,
                                   "tier": 2, "fact_sheet_ref": None}]})


def _extract_but_paraphrase(prompt):
    """The model finds the claim and restates it slightly. Correct
    judgement, non-verbatim text — which parse_extraction_wire discards
    as a hallucinated claim."""
    return json.dumps({"claims": [
        {"slot_id": None, "text": "a restatement that is nowhere in the prose",
         "tier": 1, "fact_sheet_ref": None}]})


def _prose_of(prompt):
    return prompt.split(
        "DRAFTED PROSE (extract claims from this text only):\n")[1].split(
        "\n\nFACT SHEET CATALOG")[0]


def _wire_garbage(prompt):
    """Not JSON at all — the wire never parses."""
    return "I could not find any bindable claims in this section."


def _row_malformed(prompt):
    """A row whose `text` is not a string."""
    return json.dumps({"claims": [{"slot_id": None, "text": 12345, "tier": 1}]})


def _row_unknown_slot(prompt):
    """A row naming a slot the section does not have."""
    return json.dumps({"claims": [
        {"slot_id": "slot_that_does_not_exist", "text": _prose_of(prompt),
         "tier": 1, "fact_sheet_ref": None}]})


def _row_invalid_tier(prompt):
    """Verbatim text, correct slot — and a tier the schema does not allow.

    A live model returning "1" instead of 1 lands here. Before B46 this
    drop had no marker, so the row vanished and the case reported
    `not_extracted`: the model was blamed for a row it had produced."""
    return json.dumps({"claims": [
        {"slot_id": None, "text": _prose_of(prompt),
         "tier": "1", "fact_sheet_ref": None}]})


def test_a_claim_dropped_by_the_verbatim_guard_is_named_not_hidden(tmp_path,
                                                                   cases):
    """P10-F16. The auditor prompt demands verbatim text and the parser
    enforces it by dropping anything else. A model that spots the claim
    but restates it therefore scores identically to a model that stayed
    silent — and the suite's verdict, 'never extracted', points at the
    wrong subsystem.

    This is not hypothetical: cX cycle 2's five misses each returned
    ~110 output tokens, against 38 for a genuinely empty answer, so the
    model was answering and the guard was discarding.

    The fix is that the cause is reported. The distinction is exactly
    what decides whether to widen the prompt or to loosen the match."""
    dropped = _suite_run(tmp_path / "drop", cases,
                         {"claim_auditor": _extract_but_paraphrase})
    silent = _suite_run(tmp_path / "silent", cases,
                        {"claim_auditor": _extract_nothing})

    # Identical recall — this is why one number could not see it.
    assert dropped["claim_extraction_recall"] == silent["claim_extraction_recall"] == 0.0

    # ...and now distinguishable by cause.
    assert set(dropped["causes"]) == {"dropped_verbatim"}
    assert set(silent["causes"]) == {"not_extracted"}
    assert dropped["causes"] != silent["causes"]

    sample = dropped["miss_detail"][sorted(dropped["miss_detail"])[0]]
    assert sample["cause"] == "dropped_verbatim"
    assert any("not present in delivered prose" in w
               for w in sample["warnings"]), \
        "the drop must be quoted, not merely categorised"


@pytest.mark.parametrize("script,expected_cause,marker", [
    (_extract_nothing, "not_extracted", None),
    (_extract_but_paraphrase, "dropped_verbatim",
     "not present in delivered prose"),
    (_wire_garbage, "wire_unparseable", "wire unparseable"),
    (_row_malformed, "dropped_malformed", "malformed claim row"),
    (_row_unknown_slot, "dropped_unknown_slot", "unknown slot"),
    (_row_invalid_tier, "dropped_invalid_tier", "invalid tier"),
])
def test_every_cause_is_reachable_through_the_real_parser(
        tmp_path, cases, script, expected_cause, marker):
    """Each cause driven end to end through the REAL emitter, not asserted
    against a hand-built warning list.

    This is what B46 found missing: only `dropped_verbatim` was bound this
    way, so rewording any of the other warnings would have degraded the
    taxonomy to `not_extracted` with `make check` still green — the exact
    P10-F16 failure, re-armed. Every one of these scripts scores recall
    0.0; only the cause tells them apart, which is the whole claim the
    diagnostic run is about to rest on."""
    report = _suite_run(tmp_path / expected_cause, cases,
                        {"claim_auditor": script})

    assert report["claim_extraction_recall"] == 0.0, (
        "every script here should miss everything — otherwise the cause "
        "under test is not the reason for the miss")
    assert set(report["causes"]) == {expected_cause}
    assert report["misses"], "no misses to describe — vacuous"

    detail = report["miss_detail"][sorted(report["miss_detail"])[0]]
    assert detail["cause"] == expected_cause
    assert detail["unmarked_warnings"] == [], (
        "the parser emitted a warning the taxonomy cannot name")

    if marker is None:                       # the genuinely-silent script
        assert detail["warnings"] == []
        assert detail["n_claims"] == 0
        assert detail["causes_matched"] == []
    else:
        assert any(marker in w for w in detail["warnings"]), \
            "the drop must be QUOTED, not merely categorised"
        assert expected_cause in detail["causes_matched"]


def test_a_miss_records_the_wire_that_produced_it(tmp_path, cases):
    """C4/B46. The run log stores tokens, never response text — so after a
    funded live re-baseline there would be no artifact showing whether the
    model answered at all, and a cause recorded as `not_extracted` could
    not be re-adjudicated without re-spending.

    The distinction this preserves is exactly the one cX cycle 2 had to
    make by inference: five misses at ~110 output tokens against 38 for a
    genuinely empty answer. With the wire recorded, that reading is a
    lookup instead of a deduction."""
    answered = _suite_run(tmp_path / "answered", cases,
                          {"claim_auditor": _extract_but_paraphrase})
    silent = _suite_run(tmp_path / "silent", cases,
                        {"claim_auditor": _extract_nothing})

    a = answered["miss_detail"][sorted(answered["miss_detail"])[0]]
    s = silent["miss_detail"][sorted(silent["miss_detail"])[0]]

    # The model DID answer — the wire proves it, independently of the cause.
    assert a["wire_excerpt"] and "restatement" in a["wire_excerpt"]
    assert a["output_tokens"] is not None
    # ...and the silent one is visibly empty rather than merely labelled.
    assert s["wire_excerpt"] is not None
    assert "claims" in s["wire_excerpt"]
    assert a["wire_excerpt"] != s["wire_excerpt"], (
        "if the two wires were identical the record could not tell an "
        "answering model from a silent one — which is the whole point")


def test_the_wire_excerpt_is_capped(tmp_path, cases):
    """A baseline is a diff-reviewable record, not a transcript dump."""
    from engine.evals.cases import WIRE_EXCERPT_CHARS, wire_excerpt

    assert wire_excerpt(None) is None
    short = '{"claims": []}'
    assert wire_excerpt(short) == short          # untouched below the cap

    long = "x" * (WIRE_EXCERPT_CHARS + 500)
    capped = wire_excerpt(long)
    assert len(capped) < len(long)
    assert capped.startswith("x" * WIRE_EXCERPT_CHARS)
    assert "+500 chars" in capped, \
        "truncation must be visible — a silently clipped wire reads as a " \
        "complete one and would be re-adjudicated wrongly"


def test_production_validation_never_captures_the_wire():
    """`capture` is an eval-only seam. If a production caller ever passed
    one, raw model output would start landing in pursuit artifacts — the
    opposite of the anonymization posture, and not something the eval
    baselines' synthetic-only guarantee would cover."""
    import ast
    import inspect

    from engine.validation import validate as validate_mod

    src = inspect.getsource(validate_mod)
    tree = ast.parse(src)

    callers = [n for n in ast.walk(tree)
               if isinstance(n, ast.Call)
               and isinstance(n.func, ast.Name)
               and n.func.id == "run_claim_audit"]
    assert callers, "run_claim_audit is not called in validate.py — test stale"
    for call in callers:
        assert not any(kw.arg == "capture" for kw in call.keywords), (
            "the production audit path passes `capture` — model output "
            "would be retained outside the eval harnesses")

    # And the seam defaults to off, so a new caller has to opt in.
    sig = inspect.signature(validate_mod.run_claim_audit)
    assert sig.parameters["capture"].default is None

    # Repo-wide: the seam is opt-in for the EVAL harnesses alone. The
    # original guard scanned only validate.py and only bare-name calls, so
    # a capture-passing caller in any other module — or an attribute call —
    # was invisible (pre-P12 audit, B49). Scan every engine module; the two
    # harnesses that legitimately capture are allowlisted by path.
    from pathlib import Path

    engine_root = Path(validate_mod.__file__).resolve().parents[1]
    harnesses = {engine_root / "evals" / "claim_extraction.py",
                 engine_root / "validation" / "poison.py"}
    offenders = []
    for path in sorted(engine_root.rglob("*.py")):
        if path in harnesses:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            callee = (node.func.id if isinstance(node.func, ast.Name)
                      else node.func.attr
                      if isinstance(node.func, ast.Attribute) else None)
            if callee == "run_claim_audit" and any(
                    kw.arg == "capture" for kw in node.keywords):
                offenders.append(str(path.relative_to(engine_root.parent)))
    assert offenders == [], (
        f"non-harness modules pass `capture` to run_claim_audit — raw model "
        f"output would be retained outside the eval harnesses: {offenders}")


def test_every_warning_the_parser_emits_is_nameable_by_the_taxonomy():
    """Structural guard: read the emitter's source and require that every
    warning it can produce is classified.

    A drop site with no marker does not report as 'unknown' — it falls
    through to `not_extracted` and reads as 'the model never produced this
    claim'. That is how the invalid-tier drop hid for two phases (B46).
    Reading the source means a NEW drop site fails here the day it lands,
    rather than the day someone notices a suspicious cause histogram."""
    import ast
    import inspect

    from engine.evals.cases import _DEGRADE_MARKERS, _DROP_MARKERS
    from engine.validation import claims as claims_mod

    tree = ast.parse(inspect.getsource(claims_mod.parse_extraction_wire))

    def literal_text(node):
        """The f-string's constant parts — the only bit a marker matches."""
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.JoinedStr):
            return "".join(v.value for v in node.values
                           if isinstance(v, ast.Constant)
                           and isinstance(v.value, str))
        return ""

    emitted = []
    for node in ast.walk(tree):
        # Any method call on `warnings`. Fail CLOSED on forms the walk
        # cannot read: the original guard matched `.append` alone, and a
        # drop site added via `warnings.extend([...])` slipped straight
        # through while the docstring promised day-it-lands detection
        # (proven by mutation in the pre-P12 audit, B49).
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "warnings"):
            if node.func.attr == "append":
                emitted.append(literal_text(node.args[0]))
            elif node.func.attr == "extend":
                assert len(node.args) == 1 and isinstance(
                    node.args[0], ast.List), (
                    "warnings.extend(<non-literal>) — the guard cannot read "
                    "what this emits; use a literal list or teach the guard")
                emitted += [literal_text(e) for e in node.args[0].elts]
            else:
                raise AssertionError(
                    f"unrecognized warnings mutation `.{node.func.attr}` — "
                    "a drop site this guard cannot see; teach the guard "
                    "before landing it")
        # warnings += [...] — the augmented-assign spelling of extend.
        if (isinstance(node, ast.AugAssign)
                and isinstance(node.target, ast.Name)
                and node.target.id == "warnings"):
            assert isinstance(node.value, ast.List), (
                "warnings += <non-literal> — the guard cannot read what "
                "this emits; use a literal list or teach the guard")
            emitted += [literal_text(e) for e in node.value.elts]
        # Rebinding (`warnings = warnings + [...]`) would also evade the
        # walk; the only assignment the emitter makes is the empty init.
        if (isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "warnings"
                        for t in node.targets)):
            raise AssertionError(
                "`warnings` is rebound mid-function — the guard reads only "
                "the init plus append/extend/+=; teach it before landing this")
        # the early-return form: return [], [<f-string>]
        if (isinstance(node, ast.Return)
                and isinstance(node.value, ast.Tuple)
                and len(node.value.elts) == 2
                and isinstance(node.value.elts[1], ast.List)):
            emitted += [literal_text(e) for e in node.value.elts[1].elts]

    emitted = [w for w in emitted if w]
    assert len(emitted) >= 6, (
        f"expected every drop site plus the degrade; found {len(emitted)} — "
        "the AST walk is not seeing the emitter")

    drop_markers = [m for _, m in _DROP_MARKERS]
    unnameable = [w for w in emitted
                  if not any(m in w for m in drop_markers + list(_DEGRADE_MARKERS))]
    assert unnameable == [], (
        "parse_extraction_wire emits warnings the cause taxonomy cannot "
        f"name, so they would report as 'not_extracted': {unnameable}")

    # ...and no marker is dead: each one must match something real.
    unused = [m for m in drop_markers if not any(m in w for w in emitted)]
    assert unused == [], (
        f"_DROP_MARKERS entries matching no warning the parser emits: {unused} "
        "— a renamed warning leaves a marker pointing at nothing")

    # The degrade is classified as a degrade, not as a drop. The claim
    # SURVIVES with ref=None, so calling it a drop would blame the parser
    # for a row it kept.
    degrades = [w for w in emitted
                if any(m in w for m in _DEGRADE_MARKERS)]
    assert len(degrades) == 1
    assert not any(m in degrades[0] for m in drop_markers)


def test_miss_detail_separates_never_extracted_from_tiered_down(tmp_path,
                                                                cases):
    """The two causes of a miss take OPPOSITE prompt edits — widen what
    counts as a claim, versus move the tier boundary — and a single recall
    number cannot tell them apart. The first live cycle needed exactly
    this distinction, so the report carries it."""
    silent = _suite_run(tmp_path / "a", cases,
                        {"claim_auditor": _extract_nothing})
    assert silent["misses"], "no misses to describe — the test is vacuous"
    assert {d["cause"] for d in silent["miss_detail"].values()} == {
        "not_extracted"}
    assert all(d["n_claims"] == 0 and d["tiers_extracted"] == []
               for d in silent["miss_detail"].values())

    downgraded = _suite_run(tmp_path / "b", cases,
                            {"claim_auditor": _extract_as_tier_two})
    assert downgraded["misses"] == silent["misses"], \
        "both scripts must miss the same cases — only the CAUSE differs"
    assert {d["cause"] for d in downgraded["miss_detail"].values()} == {
        "tiered_down"}
    assert all(d["tiers_extracted"] == [2]
               for d in downgraded["miss_detail"].values())


def test_per_mode_rows_sum_to_the_should_extract_half(tmp_path, cases):
    report = _suite_run(tmp_path, cases, {"claim_auditor": _extract_nothing})
    should = sum(1 for c in cases if c["expected"]["must_flag"])
    assert sum(b["total"] for b in report["by_mode"].values()) == should


def test_the_suite_runs_as_regression_bench(tmp_path, cases):
    """Eval dollars never enter the production cost series (O3/B34(16))."""
    _report = _suite_run(tmp_path, cases, {"claim_auditor": _extract_nothing})
    run = tmp_path / "extract" / "runs" / "run_0001" / "run.jsonl"
    header = json.loads(run.read_text(encoding="utf-8").splitlines()[0])
    assert header["run"]["mode"] == "regression_bench"


def test_baseline_refuses_a_stale_comparison(tmp_path, cases):
    from engine.evals.claim_extraction import (code_fingerprint,
                                                model_fingerprint)

    path = tmp_path / "baseline.json"
    report = {"claim_extraction_recall": 0.5, "claim_over_extraction_rate": 0.0,
              "prompts_fingerprint": prompts_fingerprint(),
              "cases_fingerprint": cases_fingerprint(cases),
              "model_fingerprint": model_fingerprint(),
              "code_fingerprint": code_fingerprint()}
    write_baseline(report, path)
    write_lock(path, suite="claim_extraction_set", run_id=None, at=AT)  # P2-35
    assert check_baseline(path, cases=cases)["claim_extraction_recall"] == 0.5

    # The set moved under the guard.
    with pytest.raises(BaselineMismatch):
        check_baseline(path, cases=cases[:-1])

    # The MODEL moved under the guard (P10-F14) — same prompt, same
    # cases, different sampling. Neither of the other two can see it.
    write_baseline(dict(report, model_fingerprint="0" * 64), path)
    with pytest.raises(BaselineMismatch, match="sampling parameters"):
        check_baseline(path, cases=cases)

    # The SCORING CODE moved under the guard (P11-C7) — same prompt,
    # same cases, same model, a different parser. None of the other three
    # is code, so none of them can see it.
    write_baseline(dict(report, code_fingerprint="0" * 64), path)
    with pytest.raises(BaselineMismatch, match="SCORING CODE"):
        check_baseline(path, cases=cases)

    # An unfingerprinted baseline cannot prove what it measured.
    write_baseline({"claim_extraction_recall": 0.99}, path)
    with pytest.raises(BaselineMismatch):
        check_baseline(path, cases=cases)


def test_no_baseline_reads_as_unmeasured_never_as_zero(tmp_path):
    with pytest.raises(BaselineMismatch) as caught:
        check_baseline(tmp_path / "absent.json")
    assert "not been measured live" in str(caught.value)


def test_lane_reports_the_first_live_measurement(cases):
    """F6's baseline now exists (cX cycle 1, 2026-08-10), so the lane
    reports a measured number behind its fingerprint guard rather than
    not_measured_live. The bar VALUES are pinned here on purpose: the
    lane is under its bar, and the one way that must never be resolved is
    by moving the bar."""
    from engine.evals.run import EXTRACTION_BAR, extraction_lane

    entry = extraction_lane()
    assert entry["basis"] == "live_baseline"
    assert entry["blocking"] is True
    assert entry["bar"] == {"claim_extraction_recall": 0.98,
                            "claim_over_extraction_rate_max": 0.15}
    assert EXTRACTION_BAR["claim_extraction_recall"] == 0.98
    assert "status" not in entry, "the lane must not grade itself"
    assert 0.0 <= entry["measures"]["claim_extraction_recall"] <= 1.0
    assert entry["fingerprints"]["cases_fingerprint"] == cases_fingerprint(
        cases), "the recorded baseline no longer describes the shipped cases"


def test_unmeasured_blocking_lane_cannot_promote():
    """An unmeasured blocking bar must block: 'we never checked' is not a
    pass. Driven by a synthetic lane rather than the real one, so the
    property survives the real lane becoming measured."""
    from engine.evals.release import score_suites

    unmeasured = {"basis": "live_baseline", "blocking": True,
                  "bar": {"claim_extraction_recall": 0.98},
                  "status": "not_measured_live"}
    _suites, failures = score_suites({"claim_extraction": unmeasured})
    assert failures == ["claim_extraction.not_measured_live"]

    measured_but_short = {"basis": "live_baseline", "blocking": True,
                          "bar": {"claim_extraction_recall": 0.98},
                          "measures": {"claim_extraction_recall": 0.8235}}
    _suites, failures = score_suites({"claim_extraction": measured_but_short})
    assert failures == ["claim_extraction.claim_extraction_recall"]


def _shingles(text, n=6):
    words = " ".join(text.lower().split()).split()
    return {" ".join(words[i:i + n]) for i in range(len(words) - n + 1)}


def test_anti_memorization_no_case_phrase_reaches_the_prompts(cases):
    """B34(16), and it bites hardest right here: the close step tunes the
    auditor prompt AGAINST this set, so a prompt carrying any of its
    wording would be scoring its own memory and the recall number would
    mean nothing.

    Stronger than the poison set's whole-claim sweep on purpose. Nobody
    pastes an entire case sentence into a prompt; the realistic failure is
    lifting a distinctive PHRASE while writing an instruction, so the
    sweep runs over six-word spans and covers both case sets against both
    prompt files."""
    poison_cases = json.loads(
        (CASES_PATH.parents[1] / "poison" / "cases.json")
        .read_text(encoding="utf-8"))
    prompts = " ".join(
        (ROOT / "prompts" / agent / "prompt.md").read_text(encoding="utf-8")
        for agent in ("claim_auditor", "claim_verifier"))
    prompt_spans = _shingles(prompts)
    assert prompt_spans, "prompt files read empty — the sweep would be vacuous"

    checked = 0
    for case in list(cases) + list(poison_cases):
        spans = _shingles(case["input"]["prompt_context"])
        assert spans, f"{case['case_id']}: too short to sweep"
        checked += 1
        overlap = spans & prompt_spans
        assert not overlap, (
            f"{case['case_id']}: {sorted(overlap)[0]!r} appears in a prompt "
            f"file — the suite would measure memorization, not extraction")
    assert checked >= 80, "the sweep lost a case set"


def test_extraction_cases_live_outside_the_poison_set(cases):
    """B40/D7: separate files, separate baselines. If these cases were
    added to evals/poison/cases.json, every growth of the set would stale
    the poison baseline and force a live re-measure."""
    poison = json.loads(
        (CASES_PATH.parents[1] / "poison" / "cases.json")
        .read_text(encoding="utf-8"))
    assert {c["case_id"] for c in cases}.isdisjoint(
        {c["case_id"] for c in poison})
    assert all(c["suite"] == "claim_extraction_set" for c in cases)
