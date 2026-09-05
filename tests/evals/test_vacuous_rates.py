"""P2-36 (P26b-3): no eval lane emits a rate over a vacuous denominator.

Every lane used to return 1.0 (or 0.0) when its denominator was empty —
a cases file that stopped marking any case `must_flag` would have
re-baselined to a perfect number. Now one helper, `engine.evals.cases.
rate`, refuses by name below each lane's DECLARED floor, the floors are
the committed counts (a shrink is a bar edit with a B-entry), and a
refusal reaches the release record as a typed `fail` with no measures.
"""

import json
from pathlib import Path

import pytest

from engine.evals.cases import VacuousMeasure, rate, require_n
from engine.evals.release import score_suites

ROOT = Path(__file__).resolve().parents[2]


def _cases(name: str) -> list[dict]:
    return json.loads((ROOT / "evals" / name / "cases.json")
                      .read_text(encoding="utf-8"))


def _must_flag(cases):
    return sum(1 for c in cases if c.get("expected", {}).get("must_flag"))


def test_the_helper_refuses_below_the_floor_by_name():
    assert rate(3, 4, floor=4, lane="x", of="cases") == 0.75
    assert rate(1, 3, floor=1, lane="x", of="cases", digits=None) == 1 / 3
    with pytest.raises(VacuousMeasure,
                       match="x: cases has n=3, below the declared floor 4"):
        rate(3, 3, floor=4, lane="x", of="cases")
    # Zero is never a denominator, whatever floor a lane declared.
    with pytest.raises(VacuousMeasure, match="n=0"):
        rate(0, 0, floor=0, lane="x", of="cases")
    require_n(6, 6, lane="x", of="benign controls")
    with pytest.raises(VacuousMeasure, match="benign controls has n=5"):
        require_n(5, 6, lane="x", of="benign controls")


def test_every_floor_is_the_committed_count():
    """The floors ARE the corpus sizes (B119 §4): a case removed anywhere
    reds here first, so shrinking a suite is a deliberate edit of the
    floor with its B-entry, never a quieter number."""
    from engine.evals import (claim_extraction, consistency, intake, mapper,
                              structure, trajectory, voice)
    from engine.intake import evalset as injection
    from engine.kb import evalset as anonymization
    from engine.validation import poison

    ce = _cases("claim-extraction")
    assert claim_extraction.MINIMUM_N == {
        "must_flag": _must_flag(ce), "controls": len(ce) - _must_flag(ce)}
    po = _cases("poison")
    assert poison.MINIMUM_N == {"cases": len(po), "must_flag": _must_flag(po),
                                "flagged": 1}
    ma = _cases("mapper")
    assert mapper.MINIMUM_N == {"answerable": len(ma) - _must_flag(ma),
                                "gap_cases": _must_flag(ma)}
    assert voice.MINIMUM_N == {"must_flag": _must_flag(_cases("voice"))}
    it = _cases("intake")
    assert intake.MINIMUM_N == {
        "weights": sum(len(c["expected"].get("labels", [])) for c in it),
        "date_cases": sum(1 for c in it if c["input"].get(
            "description", "").startswith("DATES")),
        "targets": len(intake.ALL_TARGETS)}
    assert structure.MINIMUM_N == {"cases": len(structure.TWIN_GOLDENS)
                                   + len(structure.ADVERSARIAL_GOLDENS)}
    assert trajectory.MINIMUM_N == {"cases": len(_cases("trajectory")),
                                    "drafted_sections": 8}
    assert consistency.MINIMUM_N == {
        "code_detectable": len(consistency.CROSS_REF_CASES)}
    inj = _cases("injection")
    assert injection.MINIMUM_N == {
        "per_family": 1,
        "held_out": sum(1 for c in inj if c.get("held_out")
                        and c["expected"]["must_flag"]),
        "benign": len(inj) - _must_flag(inj)}
    assert anonymization.MINIMUM_N == {"cases": len(_cases("anonymization"))}


def _without_must_flag(name: str, tmp_path: Path) -> Path:
    kept = [c for c in _cases(name) if not c["expected"].get("must_flag")]
    path = tmp_path / name / "cases.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(kept), encoding="utf-8")
    return path


def test_voice_refuses_a_corpus_with_no_must_flag_cases(tmp_path):
    from engine.evals.voice import evaluate_voice_set

    with pytest.raises(VacuousMeasure,
                       match="voice: must_flag cases has n=0"):
        evaluate_voice_set(_without_must_flag("voice", tmp_path))


def test_mapper_refuses_a_shrunken_answerable_set(tmp_path):
    from engine.evals.mapper import evaluate_mapper_set

    cases = _cases("mapper")
    kept = [c for c in cases if c["expected"].get("must_flag")] + [
        c for c in cases if not c["expected"].get("must_flag")][:10]
    path = tmp_path / "mapper.json"
    path.write_text(json.dumps(kept), encoding="utf-8")
    with pytest.raises(VacuousMeasure,
                       match="mapper: answerable cases has n=10, below"):
        evaluate_mapper_set(path)


def test_injection_refuses_a_corpus_with_no_held_out_attacks(tmp_path):
    from engine.intake.evalset import evaluate_injection_set

    kept = [c for c in _cases("injection")
            if not (c.get("held_out") and c["expected"]["must_flag"])]
    path = tmp_path / "injection.json"
    path.write_text(json.dumps(kept), encoding="utf-8")
    with pytest.raises(VacuousMeasure, match="held-out attack cases"):
        evaluate_injection_set(path)


def test_trajectory_refuses_an_emptied_case_file(tmp_path):
    from engine.evals.trajectory import evaluate_trajectory_set

    path = tmp_path / "trajectory.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(VacuousMeasure, match="trajectory: cases has n=0"):
        evaluate_trajectory_set(path)


def test_intake_refuses_a_corpus_that_states_no_weights(tmp_path):
    from engine.evals.intake import evaluate_intake_set

    kept = [c for c in _cases("intake") if not c["expected"].get("labels")]
    path = tmp_path / "intake.json"
    path.write_text(json.dumps(kept), encoding="utf-8")
    with pytest.raises(VacuousMeasure, match="intake: golden weights"):
        evaluate_intake_set(path)


def test_code_constant_lanes_refuse_an_emptied_roster(tmp_path, monkeypatch):
    from engine.evals import consistency, structure

    monkeypatch.setattr(consistency, "CROSS_REF_CASES", [])
    with pytest.raises(VacuousMeasure,
                       match="consistency: code-detectable cases has n=0"):
        consistency.evaluate_consistency_set()
    monkeypatch.setattr(structure, "TWIN_GOLDENS", {})
    monkeypatch.setattr(structure, "ADVERSARIAL_GOLDENS", {})
    monkeypatch.setattr(structure, "build_adversarial", lambda workdir: {})
    with pytest.raises(VacuousMeasure,
                       match="structure: golden cases has n=0"):
        structure.evaluate_structure_set(tmp_path)


def test_the_live_arm_refuses_a_vacuous_corpus_before_spending(
        tmp_path, monkeypatch):
    """The two live lanes are guarded at the ARM, before a single call:
    their suite functions sit inside the scoring-code lock (P11-C7), so
    a guard edited into them would stale the baseline it protects. A
    poison corpus with no must_flag half never runs, spends nothing,
    and writes no baseline."""
    from engine.evals.rebaseline import RebaselineRefused, rebaseline
    from engine.validation import poison

    controls_only = [c for c in poison.load_cases()
                     if not c["expected"].get("must_flag")]
    monkeypatch.setattr(poison, "load_cases", lambda *a, **k: controls_only)

    def never(log):
        raise AssertionError("the arm spent before refusing")

    path = tmp_path / "baseline.json"
    with pytest.raises(RebaselineRefused,
                       match="poison: cases has n=30, below the declared "
                             "floor 60"):
        rebaseline("poison", make_caller=never, workspace=tmp_path / "ws",
                   at="2026-09-04T00:00:00Z", baseline_path=path)
    assert not path.exists()


def test_a_vacuous_lane_reads_fail_in_the_record(monkeypatch):
    """The refusal reaches the release record as a typed fail with NO
    measures — a blocking lane in this state cannot promote."""
    import engine.evals.voice as voice_mod
    from engine.evals.run import voice_lane

    def refuse(*_a, **_k):
        raise VacuousMeasure("voice: must_flag cases has n=0, below the "
                             "declared floor 22")

    monkeypatch.setattr(voice_mod, "evaluate_voice_set", refuse)
    entry = voice_lane()
    assert entry["status"] == "fail"
    assert "measures" not in entry
    assert entry["blocking"] is True
    assert "below the declared floor 22" in entry["detail"]
    suites, blocking = score_suites({"voice": entry})
    assert suites["voice"]["status"] == "fail"
    assert blocking == ["voice.fail"]


def test_the_committed_record_shape_carries_the_floors():
    """Every lane that measures reports `minimum_n` beside its counts,
    so the release record says what floor each number stood behind."""
    from engine.evals.run import consistency_lane, structure_lane, voice_lane

    for lane in (voice_lane, structure_lane, consistency_lane):
        entry = lane()
        assert "status" not in entry, "the lane must not grade itself"
        assert entry["measures"]["minimum_n"], lane.__name__
