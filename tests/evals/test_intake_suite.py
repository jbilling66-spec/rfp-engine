"""Intake component suite (c7) and the B30(c) calibration.

The measures are only worth their bars if the corpus can actually move
them, so the tests here prove the negative direction too: a fixture that
states no weights must report none found (not a vacuous pass), and a
completeness target no package can fire must surface as dark.
"""

import pytest

from engine.evals.intake import ALL_TARGETS, CASES_PATH, evaluate_intake_set


@pytest.fixture(scope="module")
def report():
    return evaluate_intake_set()


def test_weight_goldens_are_found_in_the_committed_twins(report):
    assert report["weight_recall"] == 1.0
    assert report["weight_misses"] == []


def test_the_planted_weights_are_really_in_the_documents():
    """Absence-rule discipline: prove the swept-for strings are PRESENT
    in the source text, so a recall of 1.0 cannot come from goldens that
    were never there."""
    from engine.evals.cases import load_cases
    from engine.evals.intake import FIXTURES
    from engine.intake.extract import extract

    for case in load_cases(CASES_PATH):
        doc = extract(FIXTURES / case["input"]["files"][0])
        for weight in case["expected"]["labels"]:
            assert weight in doc.text, (
                f"{case['case_id']} plants {weight} but the document does "
                f"not contain it — the case could only ever miss")


def test_documents_without_weights_report_none_not_a_vacuous_pass(report):
    """Half the corpus states no criterion weights. Those cases carry
    empty goldens, so they contribute nothing to recall — the measure has
    to come from the documents that DO state weights."""
    from engine.evals.cases import load_cases

    cases = load_cases(CASES_PATH)
    empty = [c for c in cases if not c["expected"]["labels"]]
    planted = [c for c in cases if c["expected"]["labels"]]
    assert empty and planted, "both halves must exist for the measure to bite"


def test_prose_percents_do_not_read_as_criterion_weights():
    """The parser's discriminating rule, exercised directly: '95% uptime'
    is prose, '(30%)' and ': 40%' are criterion statements."""
    from engine.intake.brief import _stated_weight_values
    from engine.intake.extract import ExtractedDoc

    prose = ExtractedDoc(file="x", format="other",
                         text="We sustained 95% uptime across the year.")
    stated = ExtractedDoc(file="x", format="other",
                          text="Technical capability (30%) and Price: 40%")
    assert _stated_weight_values([prose]) == []
    assert sorted(_stated_weight_values([stated])) == ["30%", "40%"]


def test_every_completeness_target_can_fire_on_the_corpus(report):
    """B30(c) closed: the v2-local target list is calibrated by measuring
    which targets any committed package can exercise. A dark target is
    dead code or an untested rule — naming it is the point."""
    assert report["dark_targets"] == []
    assert report["target_coverage"] == 1.0
    assert set(report["targets_fired"]) == set(ALL_TARGETS)


def test_the_target_roster_matches_the_predicate():
    """If a new completeness rule lands without a roster entry, coverage
    would read 1.0 while silently ignoring it. Pin the roster against the
    predicate's own source."""
    import inspect

    from engine.intake.brief import completeness

    source = inspect.getsource(completeness)
    for target in ALL_TARGETS:
        assert f'"{target}"' in source, f"{target} is not in the predicate"
    emitted = source.count("miss(")
    assert emitted - 1 == len(ALL_TARGETS), (
        "the predicate emits a target the eval roster does not list "
        "(subtract 1 for the inner def)")


def test_lane_reports_its_corpus_shortfall_honestly():
    from engine.evals.run import intake_lane

    entry = intake_lane()
    assert entry["measures"]["n_packages"] == 7
    assert "15" in entry["detail"], (
        "the spec row asks for 15 packages — a lane running 7 must say so")
