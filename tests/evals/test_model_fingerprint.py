"""The third baseline lock (B43/P10-F14).

The prompts+cases pair cannot see a model repoint or an agent-config
change, so a recorded number could keep describing a system that had
moved underneath it. This is the guard that closes that.

Context worth keeping next to the code: the reason this was written is
that cX cycle 1 reproduced P8's poison recall to four decimals while four
individual cases moved, which sent the investigation to the caller. What
it found there — that the frontier model does not accept a `temperature`
parameter at all — is recorded in B43 as P10-F13. This fingerprint is the
part of that work that survives, and it stands on its own merits.
"""

import pytest
import yaml

import json

from engine.evals.cases import model_fingerprint
from engine.llm.config import PROMPTS_DIR

AT_STAMP = "2026-08-11T12:00:00Z"


def _paraphrasing_auditor(prompt):
    """Finds the claim, restates it — so the verbatim guard drops it. The
    scoring-code tests below need a script whose result CHANGES when that
    guard changes, which a silent or a verbatim script would not."""
    return json.dumps({"claims": [
        {"slot_id": None, "text": "a restatement that is nowhere in the prose",
         "tier": 1, "fact_sheet_ref": None}]})


def test_fingerprint_is_stable_for_an_unchanged_system():
    assert model_fingerprint("claim_auditor") == model_fingerprint(
        "claim_auditor")


def test_it_moves_when_a_tier_is_repointed_at_another_model(monkeypatch):
    before = model_fingerprint("claim_auditor")
    monkeypatch.setattr(
        "engine.llm.config.model_prices",
        lambda *a, **k: {"tiers": {"frontier": {"model": "some-other-model",
                                                "fallback": "f"}}})
    assert model_fingerprint("claim_auditor") != before


def test_it_moves_when_an_agent_config_changes(monkeypatch, tmp_path):
    """Whole-config hashing, so a setting added later is covered the day
    it is added rather than the day someone remembers to extend this."""
    before = model_fingerprint("claim_auditor")

    fake_prompts = tmp_path / "prompts"
    (fake_prompts / "claim_auditor").mkdir(parents=True)
    real = yaml.safe_load(
        (PROMPTS_DIR / "claim_auditor" / "config.yaml").read_text(
            encoding="utf-8"))
    moved = dict(real, tier="mid")  # the agent now runs on another tier
    (fake_prompts / "claim_auditor" / "config.yaml").write_text(
        yaml.safe_dump(moved), encoding="utf-8")
    monkeypatch.setattr("engine.llm.config.PROMPTS_DIR", fake_prompts)

    assert model_fingerprint("claim_auditor") != before


def test_it_distinguishes_which_agents_were_measured():
    """The poison suite runs two prompts, extraction one. Their baselines
    must not accept each other's fingerprint."""
    assert model_fingerprint("claim_auditor") != model_fingerprint(
        "claim_auditor", "claim_verifier")


def test_a_missing_agent_config_is_recorded_as_absent_not_skipped():
    """Absence must be part of the hash: an agent losing its config.yaml
    is a change, and a guard that silently ignored it would compare
    'clean' across it."""
    absent = model_fingerprint("no_such_agent")
    assert absent and absent != model_fingerprint("claim_auditor")


def test_both_suites_expose_the_lock():
    from engine.evals import claim_extraction as extraction
    from engine.validation import poison

    assert extraction.model_fingerprint() == model_fingerprint(
        "claim_auditor")
    assert poison.model_fingerprint() == model_fingerprint(
        "claim_auditor", "claim_verifier")
    assert extraction.model_fingerprint() != poison.model_fingerprint()


# ------------------------------------------------ code_fingerprint (P11-C7)

def test_scoring_code_changes_move_no_existing_fingerprint():
    """THE HOLE, demonstrated. Prompts, cases and model config are all
    DATA. None of them covers the code that turns a model response into a
    number — so loosening parse_extraction_wire's verbatim match moves
    both recall numbers while every existing lock still matches, and
    `make eval` compares a new system against an old number and calls it
    clean.

    Fully offline: the suite is driven by a scripted caller, so what is
    proven is the guard, not the model."""
    import json
    from pathlib import Path

    from engine.evals import claim_extraction as ext
    from engine.evals.cases import code_fingerprint
    from engine.kb import KBStore
    from engine.llm import FakeCaller, TracedCaller
    from engine.runlog import RunLogger
    from engine.validation import claims as claims_mod

    root = Path(__file__).resolve().parents[2]
    cases = ext.load_cases()
    before = {"prompts": ext.prompts_fingerprint(),
              "cases": ext.cases_fingerprint(cases),
              "model": ext.model_fingerprint(),
              "code": ext.code_fingerprint()}

    def _run(tmp, script):
        store = KBStore(root / "kb")
        log = RunLogger(tmp, run_id="run_0001", pursuit_id="eval")
        log.run_start(mode="regression_bench", engine_version="0.1.0",
                      config={"suite": "t"}, kb_snapshot=store.snapshot())
        caller = TracedCaller(FakeCaller(script), log, ceiling_usd=100.0)
        return ext.run_extraction_suite(store, caller, cases, at=AT_STAMP)

    import tempfile
    with tempfile.TemporaryDirectory() as td:
        script = {"claim_auditor": _paraphrasing_auditor}
        clean = _run(Path(td) / "a", script)

        # Loosen the guard: accept a paraphrase. Nothing else changes.
        real = claims_mod.parse_extraction_wire

        def lenient(text, *, section_id, prose_by_slot, catalog_ids):
            rows = json.loads(text).get("claims", [])
            return ([{"claim_id": f"c_{section_id}_01", "slot_id": None,
                      "text": r["text"], "tier": r.get("tier", 1),
                      "fact_sheet_ref": None} for r in rows], [])

        claims_mod.parse_extraction_wire = lenient
        try:
            loosened = _run(Path(td) / "b", script)
            after = {"prompts": ext.prompts_fingerprint(),
                     "cases": ext.cases_fingerprint(cases),
                     "model": ext.model_fingerprint(),
                     "code": ext.code_fingerprint()}
        finally:
            claims_mod.parse_extraction_wire = real

    # The number moved: this is a different system.
    assert clean["claim_extraction_recall"] != loosened["claim_extraction_recall"]

    # ...and the three pre-P11 locks are blind to it. THIS is the hole.
    for key in ("prompts", "cases", "model"):
        assert before[key] == after[key], (
            f"{key}_fingerprint moved — rewrite this test, it no longer "
            "demonstrates the blind side it was written for")

    # ...which the fourth lock closes.
    assert before["code"] != after["code"], (
        "code_fingerprint did not move when the scorer changed — the guard "
        "does not guard")


def test_a_renamed_scorer_breaks_the_roster_loudly():
    """An unresolvable roster entry is a broken guard, not an empty one.
    Silently hashing nothing is how a lock stops covering what it names."""
    import pytest as _pytest

    from engine.evals.cases import code_fingerprint

    with _pytest.raises(AttributeError, match="no longer exists"):
        code_fingerprint(("engine.validation.claims", "not_a_real_function"))


def test_both_suites_require_the_code_fingerprint(tmp_path):
    """C7 recorded it; C8 enforces it. The one-commit window was
    deliberate: adding a key to the required set stales every existing
    baseline, and only a live run refreshes one — so enforcement waited
    for the run that regenerated both."""
    import json

    import pytest as _pytest

    from engine.evals import claim_extraction as ext
    from engine.validation import poison as poi

    for module in (ext, poi):
        baseline = module.check_baseline()
        assert baseline["code_fingerprint"] == module.code_fingerprint()

        # A baseline WITHOUT the key is refused, not tolerated: that is
        # the pre-P11 shape, and it cannot prove which scorer produced it.
        stripped = {k: v for k, v in baseline.items()
                    if k != "code_fingerprint"}
        path = tmp_path / f"{module.__name__.split('.')[-1]}.json"
        path.write_text(json.dumps(stripped), encoding="utf-8")
        with _pytest.raises(module.BaselineMismatch, match="code_fingerprint"):
            module.check_baseline(path)


def test_the_code_lock_ignores_comments_but_not_logic():
    """P11-C8. The first version of this lock hashed raw source, so editing
    a COMMENT in a rostered function demanded a live re-measure to clear
    the guard. A lock that costs $3 after a typo fix is one people route
    around — and not crying wolf was the entire argument for hashing
    functions rather than files.

    So the lock is semantic: comments and docstrings out, structure in."""
    from engine.evals.cases import _semantic_source

    base = (
        "def f(x):\n"
        "    return x + 1\n")
    commented = (
        "def f(x):\n"
        '    """A docstring that says nothing about behaviour."""\n'
        "    # and a comment\n"
        "    return x + 1\n")
    logic_changed = (
        "def f(x):\n"
        "    return x + 2\n")

    assert _semantic_source(base) == _semantic_source(commented), \
        "a comment or docstring edit must NOT stale a baseline"
    assert _semantic_source(base) != _semantic_source(logic_changed), \
        "a logic change MUST stale it — otherwise the lock guards nothing"

    # Renaming a local is a real edit to the structure and is caught too;
    # this is deliberately conservative — false staleness is recoverable,
    # a missed change is a number describing a system that no longer runs.
    renamed = "def f(y):\n    return y + 1\n"
    assert _semantic_source(base) != _semantic_source(renamed)
