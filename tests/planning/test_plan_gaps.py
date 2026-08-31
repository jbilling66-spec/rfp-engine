"""Honest gaps (B24): the gapcase twin's off-corpus asks become open
no_content gaps with code-composed 2-line pings, joined to run-log gap
records by gap_id, with kb.empty_result as the logged precondition —
and nothing is ever auto-disposed."""

import pytest

from engine.kb import KBStore
from engine.kb.rank import tokenize
from engine.planning.confidence import confidence, verdict
from engine.runlog import read_run
from tests.planning.fixtures.plans import run_planning_package


@pytest.fixture(scope="module")
def planned(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("plan-gaps")
    pursuit, report = run_planning_package(tmp, package_id="gapcase", gate2=None)
    return tmp, pursuit, report


def _special(pursuit):
    plan = pursuit.read_artifact("plan.json")
    return next(s for s in plan["sections"]
                if s["section_id"] == "2-special-requirements")


def test_offcorpus_questions_are_really_off_corpus(planned):
    """Non-vacuous by construction: every content token of the planted
    off-corpus questions is absent from every card's catalog text. If a
    future corpus card adopts these tokens, this fails before the twin
    can silently stop gapping."""
    tmp, pursuit, _ = planned
    store = KBStore(tmp / "kb")
    catalog = set()
    for card in store.list_cards():
        text = " ".join([card.get("title", ""), card.get("summary", ""),
                         " ".join(card.get("type_tags", [])),
                         " ".join(card.get("section_types", []))])
        catalog.update(tokenize(text))
    container = pursuit.read_artifact("slots.json")
    off = [s for s in container["slots"] if s["ref_id"].startswith("2.")]
    assert len(off) == 2
    for slot in off:
        overlap = set(tokenize(slot["question_text"])) & catalog
        assert not overlap, f"{slot['ref_id']} shares tokens {overlap}"


def test_offcorpus_sections_carry_no_content_gaps(planned):
    _, pursuit, _ = planned
    section = _special(pursuit)
    gaps = section["gaps"]
    assert len(gaps) == 2
    for gap, ref in zip(gaps, ("2.0.1", "2.0.2")):
        assert gap["kind"] == "no_content"
        assert gap["status"] == "open"
        line1, line2 = gap["question_to_human"].split("\n")
        assert line1.startswith(f"[2. Special Requirements / {ref}]")
        assert "the engine will not draft around it" in line2
    assert "kb_hits" not in section  # nothing invented to fill it


def test_empty_result_is_the_logged_precondition(planned):
    _, pursuit, _ = planned
    records = read_run(pursuit.root / "runs" / "run_0004" / "run.jsonl")
    by_slot = {
        r["target"]["slot_ref_id"]: r["kb"]["empty_result"]
        for r in records
        if r["record_type"] == "kb_retrieval" and "target" in r
    }
    assert by_slot == {"1.0.1": False, "1.0.2": False,
                      "2.0.1": True, "2.0.2": True}


def test_gap_id_joins_plan_to_runlog(planned):
    _, pursuit, _ = planned
    plan_gap_ids = [g["gap_id"]
                    for s in pursuit.read_artifact("plan.json")["sections"]
                    for g in s.get("gaps", [])]
    records = read_run(pursuit.root / "runs" / "run_0004" / "run.jsonl")
    log_gap_ids = [r["gap"]["gap_id"] for r in records
                   if r["record_type"] == "gap"]
    assert plan_gap_ids == ["gap_pur_gapcase_plan_01", "gap_pur_gapcase_plan_02"]
    # Slot gaps number first, then obligation gaps — one log line each.
    assert set(plan_gap_ids) <= set(log_gap_ids)
    assert len(log_gap_ids) == len(set(log_gap_ids))
    assert records[-1]["run"]["totals"]["gaps_opened"] == len(log_gap_ids)


def test_gaps_never_auto_disposed(planned):
    """B24's non-preselection, asserted: every gap the engine writes is
    OPEN — no disposition, no reframe object, no answer, until a human
    decides at Gate 2. Non-vacuous: this pursuit has real gaps."""
    _, pursuit, _ = planned
    gaps = [g for s in pursuit.read_artifact("plan.json")["sections"]
            for g in s.get("gaps", [])]
    assert gaps
    for gap in gaps:
        assert gap["status"] == "open"
        assert "reframe" not in gap and "answer" not in gap and "note" not in gap


def test_verdict_vocabulary_and_confidence_bounds():
    """The mapper's honesty rule as a unit: no results -> no_content;
    all below the floor -> thin_content; otherwise grounded. Confidence
    maps any BM25 score into (0, 1), monotone."""
    assert verdict([]) == "no_content"
    assert verdict([0.1, 0.2]) == "thin_content"
    assert verdict([0.1, 0.4]) == "grounded"
    assert 0 < confidence(0.01) < confidence(1.0) < confidence(10.0) < 1
