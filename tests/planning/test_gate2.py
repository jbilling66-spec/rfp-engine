"""Gate 2: the four-option disposition menu (B24), plan freeze (T6),
idempotency/conflict, and rejection = redo with mandatory feedback the
replan consumes (recorded decision, 2026-08-02)."""

import pytest

from engine.contracts import request_digest
from engine.contracts import ContractError
from engine.kb import KBStore
from engine.llm import FakeCaller, TracedCaller, effective_config
from engine.planning import FROZEN_PLAN, approve_gate2, run_planning
from engine.runlog import RunLogger, read_run
from engine.version import engine_version
from tests.planning.fixtures.plans import (
    ACTOR,
    FIXTURES,
    GATE2_AT,
    make_architect_script,
    planning_extras,
    open_gate_run,
    run_planning_package,
)

_SPECIAL = "2-special-requirements"
_GAP1, _GAP2 = "gap_pur_gapcase_plan_01", "gap_pur_gapcase_plan_02"
_APPROVED_EDITS = {"dispose": [
    {"section_id": _SPECIAL, "gap_id": _GAP1, "action": "answered",
     "answer": "We hold the relevant certifications; see appendix."},
    {"section_id": _SPECIAL, "gap_id": _GAP2, "action": "reframed",
     "note": "Reframe onto our platform-reliability track record."},
]}


@pytest.fixture(scope="module")
def approved(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("gate2-approved")
    pursuit, report = run_planning_package(
        tmp, package_id="gapcase", gate2="approved_with_edits",
        notes="strong plan", edits=_APPROVED_EDITS,
    )
    return pursuit, report


@pytest.fixture(scope="module")
def pending(tmp_path_factory):
    """A gate2_pending plan for pure raise-tests: every bad call below
    must fail validation BEFORE any write, leaving this reusable."""
    tmp = tmp_path_factory.mktemp("gate2-pending")
    pursuit, _ = run_planning_package(tmp, package_id="gapcase", gate2=None)
    log = RunLogger(pursuit.root, pursuit.latest_run_id(), pursuit.pursuit_id,
                    resume=True)
    return pursuit, log


def _gaps(pursuit, name="plan.json"):
    plan = pursuit.read_artifact(name)
    section = next(s for s in plan["sections"]
                   if s["section_id"] == _SPECIAL)
    return {g["gap_id"]: g for g in section["gaps"]}


# --- approval ----------------------------------------------------------


def test_approval_stamps_gate2_and_created(approved):
    pursuit, _ = approved
    plan = pursuit.read_artifact("plan.json")
    assert plan["status"] == "approved"
    assert plan["gate2"] == {
        "approved_by": ACTOR, "at": GATE2_AT, "notes": "strong plan",
        "request_sha256": request_digest(decision="approved_with_edits",
                                         notes="strong plan",
                                         edits=_APPROVED_EDITS)}
    assert plan["created"] == GATE2_AT
    assert "gates_collapsed" not in plan["gate2"]  # False is omitted


def test_dispositions_recorded(approved):
    pursuit, _ = approved
    gaps = _gaps(pursuit)
    answered, reframed = gaps[_GAP1], gaps[_GAP2]
    assert answered["status"] == "answered"
    assert answered["answer"].startswith("We hold")
    assert "reframe" not in answered  # negative: no flag on answered
    assert reframed["status"] == "reframed"
    assert reframed["reframe"]["mandatory_review"] is True  # code-forced
    assert reframed["reframe"]["note"].startswith("Reframe onto")


def test_coverage_recomputed_with_identity(approved):
    pursuit, _ = approved
    cov = pursuit.read_artifact("plan.json")["coverage_summary"]
    assert cov["open_gaps"] == 0
    assert cov["total_requirements"] == 4
    assert cov["covered"] == 4  # answered + reframed both count covered
    assert cov["total_requirements"] == (
        cov["covered"] + cov["open_gaps"] + cov["omit_approved"]
        + cov["draft_flagged"]
    )


def test_plan_freeze_byte_equal(approved):
    pursuit, _ = approved
    assert (pursuit.root / "plan.json").read_bytes() == (
        pursuit.root / FROZEN_PLAN
    ).read_bytes()


def test_gate_line_and_artifacts(approved):
    pursuit, _ = approved
    records = read_run(pursuit.root / "runs" / "run_0004" / "run.jsonl")
    gate = next(r for r in records if r["record_type"] == "gate")
    assert gate["stage"] == "gate_2"
    assert gate["gate"] == {"which": "gate_2_plan",
                            "decision": "approved_with_edits",
                            "actor": ACTOR, "auto_approved": False,
                            "wait_ms": 0, "edits_summary": "dispose:2",
                            "notes": "strong plan"}  # P1-15
    shas = [r["artifact"]["sha256"] for r in records
            if r["record_type"] == "artifact"
            and r.get("stage") == "gate_2"]
    assert len(shas) == 2 and shas[0] == shas[1]  # plan + frozen, one hash
    assert records[-1]["run"]["status"] == "completed"


def test_identical_reapproval_converges(approved):
    pursuit, _ = approved
    log_path = pursuit.root / "runs" / "run_0004" / "run.jsonl"
    before = log_path.read_bytes()
    log = RunLogger(pursuit.root, "run_0004", pursuit.pursuit_id,
                    resume=True)
    # identical = the same REQUEST, dispositions included (P25 item 1):
    # the pre-P25 key ignored edits, so a replay carrying NO dispositions
    # converged onto the recorded ones — the silent-loss shape B95 named
    result = approve_gate2(
        pursuit, log, decision="approved_with_edits", actor=ACTOR,
        at=GATE2_AT, notes="strong plan", edits=_APPROVED_EDITS,
    )
    assert result.converged is True
    assert log_path.read_bytes() == before  # no new lines, no rewrites


def test_conflicting_decision_raises(approved):
    pursuit, _ = approved
    log = RunLogger(pursuit.root, "run_0004", pursuit.pursuit_id,
                    resume=True)
    with pytest.raises(ContractError, match="already decided"):
        approve_gate2(pursuit, log, decision="rejected", actor=ACTOR,
                      at="2026-08-03T09:00:00Z", notes="changed my mind")


def test_resubmit_with_fresh_at_converges_and_keeps_original_at(approved):
    """P0-5/P2-13 at Gate 2: the same request under a different clock
    converges on the recorded decision; different dispositions refuse."""
    pursuit, _ = approved
    log = RunLogger(pursuit.root, "run_0004", pursuit.pursuit_id,
                    resume=True)
    result = approve_gate2(
        pursuit, log, decision="approved_with_edits", actor=ACTOR,
        at="2026-08-03T09:00:00Z", notes="strong plan", edits=_APPROVED_EDITS)
    assert result.converged is True
    assert pursuit.checkpoint_payload("gate_2")["at"] == GATE2_AT
    with pytest.raises(ContractError, match="already decided"):
        approve_gate2(
            pursuit, log, decision="approved_with_edits", actor=ACTOR,
            at=GATE2_AT, notes="strong plan",
            edits={"dispose": [_APPROVED_EDITS["dispose"][0]]})


def test_same_rejection_resubmit_converges_and_a_different_one_refuses(
        tmp_path):
    """A rejection is a decision too: its identical resubmit converges on
    the checkpoint (same request, same plan), a different rejection on
    the SAME plan refuses; the replanned plan's fresh decision is the
    redo door's existing overwrite branch (proven over HTTP in
    tests/web/test_gates.py)."""
    pursuit, _ = run_planning_package(tmp_path, package_id="gapcase",
                                      gate2=None)
    log = open_gate_run(tmp_path, pursuit)
    first = approve_gate2(pursuit, log, decision="rejected", actor=ACTOR,
                          at=GATE2_AT, notes="tighten the discriminators")
    assert first.converged is False
    again = approve_gate2(pursuit, log, decision="rejected", actor=ACTOR,
                          at="2026-08-03T09:00:00Z",
                          notes="tighten the discriminators")
    assert again.converged is True
    assert pursuit.checkpoint_payload("gate_2")["at"] == GATE2_AT
    with pytest.raises(ContractError, match="already decided"):
        approve_gate2(pursuit, log, decision="rejected", actor=ACTOR,
                      at="2026-08-03T09:00:00Z", notes="a different reason")
    log.run_end(status="completed")


def test_fork_unlocked_for_p7(approved):
    """The exact predicate P7 will check: plan approved + frozen copy
    present + gate event in the log."""
    pursuit, _ = approved
    assert pursuit.read_artifact("plan.json")["status"] == "approved"
    assert (pursuit.root / FROZEN_PLAN).exists()


# --- draft_flagged + omit (the other half of the menu) ------------------


@pytest.fixture(scope="module")
def flagged(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("gate2-flagged")
    pursuit, _ = run_planning_package(
        tmp, package_id="gapcase", gate2="approved_with_edits",
        edits={"dispose": [
            {"section_id": _SPECIAL, "gap_id": _GAP1, "action": "draft_flagged",
             "note": "Best-effort draft; flag every novel claim."},
            {"section_id": _SPECIAL, "gap_id": _GAP2, "action": "omit_approved"},
        ]},
    )
    return pursuit


def test_draft_flagged_recorded_without_mandatory_review(flagged):
    gaps = _gaps(flagged)
    draft = gaps[_GAP1]
    assert draft["status"] == "draft_flagged"
    assert draft["note"].startswith("Best-effort")
    assert "reframe" not in draft  # the pairing is reframe-only
    assert gaps[_GAP2]["status"] == "omit_approved"


def test_coverage_identity_with_draft_flagged(flagged):
    """draft_flagged is NOT covered (B24: the human authorized
    acceleration, not coverage) — it gets its own visible bucket."""
    cov = flagged.read_artifact("plan.json")["coverage_summary"]
    assert cov == {"total_requirements": 4, "covered": 2, "open_gaps": 0,
                   "omit_approved": 1, "draft_flagged": 1}


# --- validation raises (all pre-write; the pending plan stays clean) ----


def test_rejection_without_notes_raises(pending):
    pursuit, log = pending
    with pytest.raises(ContractError, match="rejection requires notes"):
        approve_gate2(pursuit, log, decision="rejected", actor=ACTOR,
                      at=GATE2_AT)


def test_rejection_with_edits_raises(pending):
    pursuit, log = pending
    with pytest.raises(ContractError, match="takes no dispositions"):
        approve_gate2(pursuit, log, decision="rejected", actor=ACTOR,
                      at=GATE2_AT, notes="redo",
                      edits={"dispose": []})


def test_disposition_instruction_failures_raise(pending):
    pursuit, log = pending
    cases = [
        ({"dispose": [{"section_id": "no-such", "gap_id": _GAP1,
                       "action": "answered", "answer": "x"}]},
         "unknown section"),
        ({"dispose": [{"section_id": _SPECIAL, "gap_id": "gap_nope",
                       "action": "answered", "answer": "x"}]}, "no gap"),
        ({"dispose": [{"section_id": _SPECIAL, "gap_id": _GAP1,
                       "action": "shrug"}]}, "unknown action"),
        ({"dispose": [{"section_id": _SPECIAL, "gap_id": _GAP1,
                       "action": "answered"}]}, "requires an answer"),
        ({"dispose": [{"section_id": _SPECIAL, "gap_id": _GAP1,
                       "action": "reframed"}]}, "requires a note"),
        ({"dispose": [{"section_id": _SPECIAL, "gap_id": _GAP1,
                       "action": "draft_flagged", "answer": "sneaky"}]},
         "takes no answer"),
        ({"prune": []}, "unknown operations"),
    ]
    for edits, message in cases:
        with pytest.raises(ContractError, match=message):
            approve_gate2(pursuit, log, decision="approved_with_edits",
                          actor=ACTOR, at=GATE2_AT, edits=edits)
    # None of the failed instructions mutated the plan.
    assert all(g["status"] == "open" for g in _gaps(pursuit).values())


def test_auto_approved_guard_and_bad_at(pending):
    pursuit, log = pending
    with pytest.raises(ContractError, match="reserved for replay"):
        approve_gate2(pursuit, log, decision="approved", actor=ACTOR,
                      at=GATE2_AT, auto_approved=True)
    with pytest.raises(ContractError, match="reserved for replay"):
        approve_gate2(pursuit, log, decision="auto_approved", actor=ACTOR,
                      at=GATE2_AT)
    with pytest.raises(ValueError, match="ISO 8601"):
        approve_gate2(pursuit, log, decision="approved", actor=ACTOR,
                      at="yesterday-ish")


def test_gates_collapsed_passthrough(tmp_path):
    """The recorded per-deal toggle (B22(15) carry): True is written,
    False is omitted; the real one-screen collapse UX is P9's."""
    pursuit, _ = run_planning_package(tmp_path, package_id="gapcase",
                                      gate2=None)
    report, log = _new_planning_run_logger(tmp_path, pursuit)
    approve_gate2(pursuit, log, decision="approved", actor=ACTOR,
                  at=GATE2_AT, gates_collapsed=True)
    log.run_end(status="completed")
    gate2 = pursuit.read_artifact("plan.json")["gate2"]
    assert gate2["gates_collapsed"] is True


# --- rejection = redo with feedback ------------------------------------


def _new_planning_run_logger(tmp, pursuit):
    """A fresh, properly-opened run for a standalone gate decision —
    gate lines never append after a closed run's footer (P5 lesson)."""
    store = KBStore(tmp / "kb")
    log = RunLogger(pursuit.root, pursuit.new_run_id(), pursuit.pursuit_id)
    cfg = effective_config(extra=planning_extras())
    log.run_start(mode="dry_run", engine_version=engine_version(), config=cfg,
                  kb_snapshot=store.snapshot(),
                  research_mode=cfg["research_mode"])
    return None, log


def _new_planning_run(tmp, pursuit, script=None, workbook=None):
    store = KBStore(tmp / "kb")
    log = RunLogger(pursuit.root, pursuit.new_run_id(), pursuit.pursuit_id)
    caller = TracedCaller(FakeCaller(script or make_architect_script()), log)
    cfg = effective_config(extra=planning_extras())
    log.run_start(mode="dry_run", engine_version=engine_version(), config=cfg,
                  kb_snapshot=store.snapshot(),
                  research_mode=cfg["research_mode"])
    report = run_planning(pursuit, caller, log, store, workbook=workbook)
    return report, log


def test_rejection_redo_cycle_path_a(tmp_path):
    """Reject -> feedback recorded and surfaced -> planning genuinely
    reruns -> re-approval succeeds and freezes."""
    pursuit, _ = run_planning_package(tmp_path, package_id="gapcase",
                                      gate2=None)
    _, log = _new_planning_run_logger(tmp_path, pursuit)
    result = approve_gate2(
        pursuit, log, decision="rejected", actor=ACTOR, at=GATE2_AT,
        notes="Too thin on the special requirements — talk to the SME first.",
    )
    log.run_end(status="completed")
    assert result.frozen_path is None
    plan = pursuit.read_artifact("plan.json")
    assert plan["status"] == "draft"
    assert "gate2" not in plan and "created" not in plan
    assert not (pursuit.root / FROZEN_PLAN).exists()
    # The redo door is open: planning checkpoints cleared, feedback kept.
    completed = pursuit.completed_stages()
    assert "gate_2" in completed
    assert not completed & {"path_a_map", "path_b_outline", "pursuit_plan"}
    assert pursuit.checkpoint_payload("gate_2")["notes"].startswith("Too thin")

    report, log2 = _new_planning_run(
        tmp_path, pursuit, workbook=FIXTURES / "gapcase-twin.xlsx"
    )
    assert report.status == "complete"
    assert any("replanning after gate_2 rejection" in w for w in report.warnings)
    # Path A honesty: deterministic inputs unchanged -> same plan content.
    assert pursuit.checkpoint_payload("path_a_map")["rejection_feedback"]
    assert pursuit.read_artifact("plan.json")["status"] == "gate2_pending"

    result = approve_gate2(pursuit, log2, decision="approved", actor=ACTOR,
                           at="2026-08-03T09:00:00Z")
    log2.run_end(status="completed")
    assert result.frozen_path is not None
    assert pursuit.read_artifact("plan.json")["status"] == "approved"


def test_rejection_feedback_reaches_path_b_replan(tmp_path):
    """The full loop on the path where feedback changes the outcome: the
    feedback text reaches the architect prompt, the redo outline differs
    (a section titled from the quoted phrase appears), re-approval
    freezes."""
    script = make_architect_script()
    pursuit, _ = run_planning_package(tmp_path, package_id="pdf",
                                      script=script, gate2=None)
    round1 = pursuit.read_artifact("plan.json")
    _, log = _new_planning_run_logger(tmp_path, pursuit)
    approve_gate2(
        pursuit, log, decision="rejected", actor=ACTOR, at=GATE2_AT,
        notes='Add a dedicated "Data Migration" section before the team page.',
    )
    log.run_end(status="completed")

    report, log2 = _new_planning_run(tmp_path, pursuit, script=script)
    assert report.status == "complete"

    # The feedback text reached the architect inside the lead frame.
    redo_prompt = script["outline_architect"].prompts[-1]
    assert '<pursuit_lead_context label="firm">' in redo_prompt
    assert '"Data Migration"' in redo_prompt

    round2 = pursuit.read_artifact("plan.json")
    assert round2 != round1  # the redo provably differs
    titles = [s["title"] for s in round2["sections"]]
    assert "Data Migration" in titles

    result = approve_gate2(pursuit, log2, decision="approved", actor=ACTOR,
                           at="2026-08-03T09:00:00Z")
    log2.run_end(status="completed")
    assert result.frozen_path is not None
    # Post-approval, the stage refuses to rebuild (T7 analog).
    report3, log4 = _new_planning_run(tmp_path, pursuit, script=script)
    log4.run_end(status="completed")
    assert report3.status == "refused"


# --- Gate-2 extensions: section edits + obligation waives (P9/D25) -----


@pytest.fixture()
def pending_b(tmp_path):
    """A gate2_pending Path-B plan — the only path where sections may be
    added or killed."""
    pursuit, _ = run_planning_package(tmp_path, package_id="pdf",
                                      script=make_architect_script(),
                                      gate2=None)
    _, log = _new_planning_run_logger(tmp_path, pursuit)
    return pursuit, log


class TestSectionEdits:
    def test_path_b_add_kill_edit_apply_with_same_batch_dispose(
            self, pending_b):
        pursuit, log = pending_b
        before = pursuit.read_artifact("plan.json")
        victim = before["sections"][-1]["section_id"]
        retitled = before["sections"][0]["section_id"]
        approve_gate2(
            pursuit, log, decision="approved_with_edits", actor=ACTOR,
            at=GATE2_AT, edits={
                "sections": [
                    {"op": "kill", "section_id": victim,
                     "reason": "duplicates the approach section"},
                    {"op": "edit", "section_id": retitled,
                     "title": "Executive Summary (for the Selection Board)"},
                    {"op": "add", "title": "Community Impact"},
                ],
                # The added section's code-forced gap is disposable in the
                # SAME batch — section edits apply first.
                "dispose": [
                    {"section_id": "community-impact",
                     "gap_id": f"gap_{pursuit.pursuit_id}_gate2_01",
                     "action": "draft_flagged",
                     "note": "Best effort; flag novel claims."},
                ],
            })
        log.run_end(status="completed")
        plan = pursuit.read_artifact("plan.json")
        ids = [s["section_id"] for s in plan["sections"]]
        assert victim not in ids
        assert plan["sections"][0]["title"] == (
            "Executive Summary (for the Selection Board)")
        added = next(s for s in plan["sections"]
                     if s["section_id"] == "community-impact")
        assert "source" not in added  # added at the gate: no provenance claim
        assert added["gaps"][0]["status"] == "draft_flagged"
        assert added["gaps"][0]["kind"] == "needs_sme"
        # The gate line carries the counts; the checkpoint carries the why.
        records = read_run(pursuit.root / "runs"
                           / pursuit.latest_run_id() / "run.jsonl")
        gate = next(r["gate"] for r in records if r["record_type"] == "gate")
        assert gate["edits_summary"] == "dispose:1 add:1 kill:1 edit:1"
        gap_lines = [r for r in records if r["record_type"] == "gap"]
        assert [g["gap"]["gap_id"] for g in gap_lines] == [
            f"gap_{pursuit.pursuit_id}_gate2_01"]
        assert gap_lines[0]["target"]["section_id"] == "community-impact"
        kills = pursuit.checkpoint_payload("gate_2")["section_kills"]
        assert kills == [{"section_id": victim,
                          "title": before["sections"][-1]["title"],
                          "reason": "duplicates the approach section",
                          "by": ACTOR}]
        assert (pursuit.root / FROZEN_PLAN).exists()

    def test_added_section_without_disposition_keeps_its_open_gap(
            self, pending_b):
        pursuit, log = pending_b
        approve_gate2(pursuit, log, decision="approved_with_edits",
                      actor=ACTOR, at=GATE2_AT,
                      edits={"sections": [{"op": "add", "title": "Warranty"}]})
        log.run_end(status="completed")
        plan = pursuit.read_artifact("plan.json")
        added = next(s for s in plan["sections"]
                     if s["section_id"] == "warranty")
        assert added["gaps"][0]["status"] == "open"  # rides to drafting: pends
        assert plan["coverage_summary"]["open_gaps"] >= 1

    def test_path_a_add_and_kill_refused_title_edit_applies(self, tmp_path):
        pursuit, _ = run_planning_package(tmp_path, package_id="gapcase",
                                          gate2=None)
        _, log = _new_planning_run_logger(tmp_path, pursuit)
        for op in ({"op": "add", "title": "Extra"},
                   {"op": "kill", "section_id": _SPECIAL, "reason": "x"}):
            with pytest.raises(ContractError, match="omission-disposition"):
                approve_gate2(pursuit, log, decision="approved_with_edits",
                              actor=ACTOR, at=GATE2_AT,
                              edits={"sections": [op]})
        approve_gate2(pursuit, log, decision="approved_with_edits",
                      actor=ACTOR, at=GATE2_AT,
                      edits={"sections": [
                          {"op": "edit", "section_id": _SPECIAL,
                           "title": "2. Special Requirements (renamed)"}]})
        log.run_end(status="completed")
        plan = pursuit.read_artifact("plan.json")
        section = next(s for s in plan["sections"]
                       if s["section_id"] == _SPECIAL)
        assert section["title"] == "2. Special Requirements (renamed)"

    def test_section_edit_instruction_failures_raise(self, pending_b):
        pursuit, log = pending_b
        cases = [
            ({"sections": [{"op": "kill", "section_id": "nope",
                            "reason": "x"}]}, "unknown section"),
            ({"sections": [{"op": "kill",
                            "section_id": "executive-summary"}]},
             "reason is required"),
            ({"sections": [{"op": "add"}]}, "title is required"),
            ({"sections": [{"op": "edit", "section_id": "executive-summary"}]},
             "only editable field"),
            ({"sections": [{"op": "retitle"}]}, "add|kill|edit"),
        ]
        for edits, match in cases:
            with pytest.raises(ContractError, match=match):
                approve_gate2(pursuit, log, decision="approved_with_edits",
                              actor=ACTOR, at=GATE2_AT, edits=edits)
        # every refusal left the plan untouched
        assert pursuit.read_artifact("plan.json")["status"] == "gate2_pending"


class TestObligationWaives:
    def test_waive_applies_and_stays_distinct_from_covered(self, tmp_path):
        pursuit, _ = run_planning_package(tmp_path, package_id="gapcase",
                                          gate2=None)
        plan = pursuit.read_artifact("plan.json")
        gapped = [o["id"] for o in plan.get("obligations", [])
                  if o["status"] == "gapped"]
        assert gapped, "gapcase must carry a gapped obligation (non-vacuity)"
        _, log = _new_planning_run_logger(tmp_path, pursuit)
        approve_gate2(pursuit, log, decision="approved_with_edits",
                      actor=ACTOR, at=GATE2_AT,
                      edits={"waive_obligations": [
                          {"id": gapped[0],
                           "note": "Out of scope this cycle per the lead."}]})
        log.run_end(status="completed")
        plan = pursuit.read_artifact("plan.json")
        row = next(o for o in plan["obligations"] if o["id"] == gapped[0])
        assert row["status"] == "waived"  # not covered — the D25 distinction
        assert row["note"] == "Out of scope this cycle per the lead."
        records = read_run(pursuit.root / "runs"
                           / pursuit.latest_run_id() / "run.jsonl")
        gate = next(r["gate"] for r in records if r["record_type"] == "gate")
        assert gate["edits_summary"] == "waive:1"

    def test_waive_instruction_failures_raise(self, tmp_path):
        pursuit, _ = run_planning_package(tmp_path, package_id="gapcase",
                                          gate2=None)
        plan = pursuit.read_artifact("plan.json")
        rows = plan.get("obligations", [])
        gapped = next(o["id"] for o in rows if o["status"] == "gapped")
        covered = next((o["id"] for o in rows if o["status"] == "covered"),
                       None)
        _, log = _new_planning_run_logger(tmp_path, pursuit)
        cases = [
            ([{"id": gapped}], "requires a note"),
            ([{"id": "nope", "note": "x"}], "unknown obligation"),
            ([{"id": gapped, "note": "x"},
              {"id": gapped, "note": "y"}], "already waived"),
        ]
        if covered:
            cases.append(([{"id": covered, "note": "x"}],
                          "only a gapped obligation"))
        for waives, match in cases:
            with pytest.raises(ContractError, match=match):
                approve_gate2(pursuit, log, decision="approved_with_edits",
                              actor=ACTOR, at=GATE2_AT,
                              edits={"waive_obligations": waives})
        assert pursuit.read_artifact("plan.json")["status"] == "gate2_pending"
