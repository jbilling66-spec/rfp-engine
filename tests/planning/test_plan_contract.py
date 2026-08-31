"""Every claimed pursuit-plan field has a writer (the B11 field-with-no-
writer class, applied to the whole plan contract): walk the schema's
property tree and prove each path is non-trivially written by P6 — plus
P7's drafting run for the one field it owns (sections[].draft_status,
unpinned when its writer landed, B31(6)) — across a two-plan corpus, or
is on the pinned NOT_YET_WRITTEN list with its owner named. The reverse
holds too: a NOT_YET_WRITTEN path that gains a writer must be removed
from the list (absence honesty)."""

import json
from pathlib import Path

import pytest

from tests.planning.fixtures.plans import (
    run_planning_package,
    write_prior_plan,
)

SCHEMA = json.loads(
    (Path(__file__).resolve().parents[2] / "schemas"
     / "pursuit-plan.schema.json").read_text(encoding="utf-8")
)

# Claimed by the schema, written by nothing yet — each with its owner.
NOT_YET_WRITTEN = {
    # effort_allocation CLOSED at P10/c22 (B33(3)): planning writes it
    # explicitly — weighted iff the buyer stated evaluation weights,
    # else uniform — and drafting consumes it. The pin is bidirectional,
    # so leaving it here after the writer landed would fail too.
    "sections[].kb_hits[].layer",    # mapper records kb_id+confidence; B28
    "sections[].kb_hits[].note",     # P7/P9 annotation channel
}


def _schema_paths(properties: dict, prefix: str = "") -> set[str]:
    out: set[str] = set()
    for key, spec in properties.items():
        path = f"{prefix}{key}"
        out.add(path)
        if spec.get("type") == "object" and "properties" in spec:
            out |= _schema_paths(spec["properties"], f"{path}.")
        items = spec.get("items", {})
        if items.get("type") == "object" and "properties" in items:
            out |= _schema_paths(items["properties"], f"{path}[].")
    return out


def _written_paths(obj, prefix: str = "") -> set[str]:
    out: set[str] = set()
    if isinstance(obj, dict):
        for key, value in obj.items():
            path = f"{prefix}{key}"
            out.add(path)
            out |= _written_paths(value, f"{path}.")
    elif isinstance(obj, list):
        stripped = prefix[:-1] + "[]."
        for item in obj:
            out |= _written_paths(item, stripped)
    return out


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    """Three plans that between them exercise the whole written surface:
    (1) gapcase with answered+reframed dispositions and a title-matching
    prior (precedents), then DRAFTED through the real P7 stage so
    sections[].draft_status has its writer in the corpus; (2) gapcase
    with draft_flagged (+note) and omit_approved, approved with
    gates_collapsed; (3) a Path-B outline — based_on's only writer."""
    plans = []
    tmp1 = tmp_path_factory.mktemp("contract-1")
    write_prior_plan(tmp1, section_title="1. Delivery Approach",
                     kb_ids=("kb-prior-x",))
    p1, _ = run_planning_package(
        tmp1, package_id="gapcase", gate2="approved_with_edits",
        notes="solid",
        edits={"dispose": [
            {"section_id": "2-special-requirements",
             "gap_id": "gap_pur_gapcase_plan_01", "action": "answered",
             "answer": "Certification evidence attached."},
            {"section_id": "2-special-requirements",
             "gap_id": "gap_pur_gapcase_plan_02", "action": "reframed",
             "note": "Reframe onto reliability track record."},
        ]},
    )
    from tests.drafting.fixtures.drafts import run_drafting_run
    p1, draft_report = run_drafting_run(tmp1, p1)
    assert draft_report.status == "complete"
    plans.append(p1.read_artifact("plan.json"))

    tmp2 = tmp_path_factory.mktemp("contract-2")
    from engine.planning import approve_gate2
    from tests.planning.fixtures.plans import ACTOR, GATE2_AT, open_gate_run
    p2, _ = run_planning_package(tmp2, package_id="gapcase", gate2=None)
    gapped_obligation = next(
        o["id"] for o in p2.read_artifact("plan.json")["obligations"]
        if o["status"] == "gapped")  # obligations[].note's writer (D25)
    log = open_gate_run(tmp2, p2)
    approve_gate2(
        p2, log, decision="approved_with_edits", actor=ACTOR, at=GATE2_AT,
        gates_collapsed=True,
        edits={"waive_obligations": [
            {"id": gapped_obligation,
             "note": "Accepted uncovered this cycle."}],
               "dispose": [
            {"section_id": "2-special-requirements",
             "gap_id": "gap_pur_gapcase_plan_01", "action": "draft_flagged",
             "note": "Best effort, flag novel claims."},
            {"section_id": "2-special-requirements",
             "gap_id": "gap_pur_gapcase_plan_02", "action": "omit_approved"},
        ]},
    )
    log.run_end(status="completed")
    plans.append(p2.read_artifact("plan.json"))

    # (3) A Path-B plan — based_on (E1) has its only writer on the
    # free-flow path, so the corpus needs one to prove it written.
    from tests.planning.fixtures.plans import make_architect_script
    tmp3 = tmp_path_factory.mktemp("contract-3")
    p3, report3 = run_planning_package(
        tmp3, package_id="pdf", script=make_architect_script(), gate2=None)
    assert report3.status == "complete" and report3.path == "B_free_flow"
    plans.append(p3.read_artifact("plan.json"))
    return plans


def test_every_claimed_field_has_a_writer(corpus):
    claimed = _schema_paths(SCHEMA["properties"])
    written: set[str] = set()
    for plan in corpus:
        written |= _written_paths(plan)
    unwritten = claimed - written
    assert unwritten == NOT_YET_WRITTEN, (
        f"schema fields with no writer (add a writer or pin with owner): "
        f"{sorted(unwritten - NOT_YET_WRITTEN)}; "
        f"pinned-but-now-written (unpin): "
        f"{sorted(NOT_YET_WRITTEN - unwritten)}"
    )


def test_corpus_really_exercises_the_dispositions(corpus):
    plan1, plan2 = corpus[:2]
    statuses = {g["status"] for p in (plan1, plan2)
                for s in p["sections"] for g in s.get("gaps", [])}
    assert statuses == {"answered", "reframed", "draft_flagged",
                        "omit_approved"}
    assert any("precedents" in s for s in plan1["sections"])
    assert plan2["gate2"]["gates_collapsed"] is True
