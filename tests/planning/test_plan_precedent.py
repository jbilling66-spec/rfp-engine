"""The precedent lane (the owner's build-now override, B28): advisory hints
derived from approved sibling plans — exact-match only, never
auto-applied, skipping unapproved and unreadable siblings.

One chained workspace holds four priors written BEFORE the planning run
(the real production order); the advisory invariant compares against a
prior-free baseline workspace.
"""

import pytest

from tests.planning.fixtures.plans import run_planning_package, write_prior_plan

# The structured twin's own first question, verbatim (the exact-match key).
_MATCH_QUESTION = "Provide an overview of your firm and ERP practice."


@pytest.fixture(scope="module")
def planned(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("plan-precedent")
    write_prior_plan(tmp, pursuit_id="pur_prior_q",
                     question_text=_MATCH_QUESTION,
                     kb_ids=("kb-prior-a", "kb-prior-b"))
    write_prior_plan(tmp, pursuit_id="pur_prior_title",
                     section_title="2. Integration",
                     kb_ids=("kb-prior-c",))
    write_prior_plan(tmp, pursuit_id="pur_prior_draft",
                     question_text=_MATCH_QUESTION, status="draft")
    write_prior_plan(tmp, pursuit_id="pur_prior_unrelated",
                     question_text="Describe your lunar catering approach.")
    # An unreadable sibling: a directory with a corrupt plan.json.
    corrupt = tmp / "pur_prior_corrupt"
    corrupt.mkdir()
    (corrupt / "plan.json").write_text("{not json", encoding="utf-8")

    pursuit, report = run_planning_package(tmp, package_id="xlsx", gate2=None)
    return pursuit, report


def _sections(pursuit):
    return {s["section_id"]: s
            for s in pursuit.read_artifact("plan.json")["sections"]}


def test_exact_question_match_carries_prior_id_and_kb_ids(planned):
    pursuit, _ = planned
    company = _sections(pursuit)["1-company-background"]
    hits = [p for p in company["precedents"]
            if p["pursuit_id"] == "pur_prior_q"]
    assert len(hits) == 1
    assert hits[0]["section_id"] == "prior-section"
    assert hits[0]["kb_ids"] == ["kb-prior-a", "kb-prior-b"]
    assert hits[0]["note"] == "exact question match"


def test_exact_title_match(planned):
    pursuit, _ = planned
    integration = _sections(pursuit)["2-integration"]
    hits = [p for p in integration["precedents"]
            if p["pursuit_id"] == "pur_prior_title"]
    assert len(hits) == 1
    assert hits[0]["note"] == "exact title match"


def test_unapproved_and_unrelated_and_corrupt_siblings_never_hint(planned):
    pursuit, report = planned
    all_hint_ids = {p["pursuit_id"]
                    for s in _sections(pursuit).values()
                    for p in s.get("precedents", [])}
    assert "pur_prior_draft" not in all_hint_ids      # approved-only
    assert "pur_prior_unrelated" not in all_hint_ids  # exact-only
    assert "pur_prior_corrupt" not in all_hint_ids
    # The corrupt sibling is named, never crashed on.
    assert any("pur_prior_corrupt" in w for w in report.warnings)
    # No hint on the pricing section: nothing matches it.
    assert "precedents" not in _sections(pursuit)["3-pricing"]


def test_two_real_chains_no_false_cross_hints(tmp_path):
    """The cross-sibling negative on two GENUINE chains in one root: a
    Gate-2-approved free-flow plan sits beside a designated pursuit, the
    scan walks it for real, and no hint crosses (no shared question
    text, no shared titles). Non-vacuous: the sibling IS approved and IS
    scanned — only the exact-match rule keeps it silent."""
    pdf_pursuit, _ = run_planning_package(tmp_path, package_id="pdf",
                                          gate2="approved")
    assert pdf_pursuit.read_artifact("plan.json")["status"] == "approved"
    xlsx_pursuit, report = run_planning_package(tmp_path, package_id="xlsx",
                                                gate2=None)
    assert report.status == "complete"
    hints = {p["pursuit_id"]
             for s in xlsx_pursuit.read_artifact("plan.json")["sections"]
             for p in s.get("precedents", [])}
    assert "pur_pdf" not in hints


def test_hints_are_advisory_only(planned, tmp_path):
    """The invariant that makes the lane safe (B24 posture): a matching
    prior changes NOTHING except precedents[] — same gaps, same
    coverage, same kb_hits, same obligations as a prior-free build."""
    pursuit, _ = planned
    baseline_pursuit, _ = run_planning_package(
        tmp_path, package_id="xlsx", gate2=None
    )
    with_prior = pursuit.read_artifact("plan.json")
    baseline = baseline_pursuit.read_artifact("plan.json")

    def strip(plan):
        out = dict(plan)
        out["sections"] = [
            {k: v for k, v in s.items() if k != "precedents"}
            for s in plan["sections"]
        ]
        return out

    assert strip(with_prior) == strip(baseline)
    assert with_prior != baseline  # the hints ARE there (non-vacuous)
