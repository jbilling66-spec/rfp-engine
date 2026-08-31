"""The injection suite (B34(18), closes B30(c)): novel paraphrases per
attack family against the REAL deterministic screen; the recorded report
is drift-tested so a lexicon edit forces a conscious re-record. The
honest-suite property: recall is strictly between 0 and 1 — a suite the
regexes match by construction (recall 1.0 by design) would be fiction,
and a suite nothing catches would be vacuous."""

import json

import pytest

from engine.intake.evalset import (
    RECORDED_PATH,
    cases_fingerprint,
    evaluate_injection_set,
    lexicon_fingerprint,
    load_cases,
)

FAMILIES = {"meta_ignore_instructions", "meta_reveal_prompt",
            "meta_new_instructions", "internal_material_demand"}


@pytest.fixture(scope="module")
def cases():
    return load_cases()


def test_cases_validate_with_held_out_quota(cases):
    # 21 at P8 + 8 comment-shaped cases at P10 (B37 risk 5): guest
    # comments now reach a model prompt, so the suite carries attacks
    # shaped like review comments — payload behind praise or critique.
    assert len(cases) == 29
    assert sum(1 for c in cases if c["held_out"]) / len(cases) >= 0.2
    benign = [c for c in cases if not c["expected"]["must_flag"]]
    assert len(benign) == 6  # precision controls exist
    for case in cases:
        family = case["expected"]["labels"][0]
        assert family in FAMILIES | {"benign_control"}


def test_every_family_has_cases_and_at_least_one_close_paraphrase(cases):
    by_family: dict[str, int] = {}
    for case in cases:
        if case["expected"]["must_flag"]:
            by_family[case["expected"]["labels"][0]] = \
                by_family.get(case["expected"]["labels"][0], 0) + 1
    assert set(by_family) == FAMILIES
    assert all(n >= 4 for n in by_family.values())


def test_recall_is_honest_not_green_by_construction():
    report = evaluate_injection_set()
    assert 0.0 < report["overall_recall"] < 1.0, \
        "a suite the lexicon catches (or misses) entirely proves nothing"
    assert any(b["caught"] < b["total"] for b in report["families"].values())
    assert any(b["caught"] > 0 for b in report["families"].values())
    assert report["false_positives"] == []  # the benign controls stay clean


def test_recorded_report_matches_a_fresh_run(cases):
    # The drift lock: edit the lexicon or the cases and this fails until
    # `python -c "from engine.intake.evalset import write_recorded;
    # write_recorded()"` re-derives the record CONSCIOUSLY.
    committed = json.loads(RECORDED_PATH.read_text(encoding="utf-8"))
    assert committed == evaluate_injection_set()
    assert committed["lexicon_fingerprint"] == lexicon_fingerprint()
    assert committed["cases_fingerprint"] == cases_fingerprint(cases)


def test_comment_shaped_attacks_are_carried_and_caught(cases):
    """B37 risk 5: the guest-comment lane put untrusted text in front of
    a model, so the suite must carry attacks wrapped in review-comment
    framing. These were authored AFTER the lexicon was extended and the
    patterns were not touched afterward — so catching them is
    generalization, not fitting."""
    from engine.intake.extract import ExtractedDoc
    from engine.intake.screen import screen

    comment_cases = [c for c in cases if c["case_id"].startswith("inj_cmt_")]
    assert len(comment_cases) == 8
    for case in comment_cases:
        fired = bool(screen(ExtractedDoc(
            file="x", format="other",
            text=case["input"]["prompt_context"])))
        assert fired is case["expected"]["must_flag"], case["case_id"]


def test_a_reviewer_retracting_their_own_comment_never_flags(cases):
    """The hardest benign control: 'disregard my earlier comment' is
    literally an ignore-shaped sentence, and flagging it would train
    reviewers to click past the badge that matters."""
    from engine.intake.extract import ExtractedDoc
    from engine.intake.screen import screen

    case = next(c for c in cases if c["case_id"] == "inj_cmt_ben_001")
    assert not screen(ExtractedDoc(file="x", format="other",
                                   text=case["input"]["prompt_context"]))


def test_held_out_recall_is_reported_separately():
    """B40/D9: the lexicon may only be tuned against the tuning half, so
    the held-out number is the one that says whether it generalizes.
    Reporting it beside overall recall is what makes pattern-fitting
    visible instead of flattering."""
    report = evaluate_injection_set()
    assert report["held_out_total"] >= 4
    assert 0.0 < report["held_out_recall"] < 1.0, (
        "held-out recall at 0 or 1 means the split has stopped informing")
    assert report["held_out_recall"] < report["overall_recall"], (
        "tuning lifted the tuning half more than the held-out half — the "
        "honest shape; if these ever equalize, say so deliberately")


def test_per_family_rows_sum_to_the_flagged_half(cases):
    report = evaluate_injection_set()
    flagged = sum(1 for c in cases if c["expected"]["must_flag"])
    assert sum(b["total"] for b in report["families"].values()) == flagged
    assert report["benign_total"] == len(cases) - flagged
