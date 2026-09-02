"""The extracted stage-order authority (B37/D26) and the first writers
of the dormant run statuses (D15): a driver with no gate decider stops
`awaiting_gate` instead of guessing, and a drafting run left with
awaiting_disposition sections ends `awaiting_gap` — "completed" would
lie. The behavior-identical half of the extraction is proven elsewhere:
tests/slice passed UNEDITED (incl. byte-identity) over the delegating
runner."""

from engine.cli.slice import (
    ACTOR,
    DEFAULT_AT,
    DEMO_PACK,
    DEMO_RAMBLE,
    DEMO_WORKBOOK,
    KB_ROOT,
    _canned_dispositions,
    _extras,
)
from engine.cli.slice_script import ci_script
from engine.intake.brief import IntakeDoc, IntakePackage
from engine.llm import FakeCaller, TracedCaller
from engine.pipeline import advance
from engine.runlog import read_run
from engine.workspace import PursuitDir


def _make_caller(log):
    return TracedCaller(FakeCaller(ci_script()), log)


def _demo_package(_pursuit):
    return IntakePackage(
        pursuit_id="pur_demo",
        docs=[IntakeDoc(path=DEMO_WORKBOOK, kind="rfp_main")],
        ramble=DEMO_RAMBLE.read_text(encoding="utf-8"))


def _advance(pursuit, **overrides):
    kwargs = dict(make_caller=_make_caller, mode="dry_run", kb_root=KB_ROOT,
                  at=DEFAULT_AT, extras=_extras,
                  intake_package=_demo_package, research_pack=DEMO_PACK,
                  workbook=DEMO_WORKBOOK,
                  decide_gate0=lambda p: {"decision": "auto_approved",
                                          "auto_approved": True},
                  decide_gate1=lambda p: {"decision": "approved"},
                  decide_gate2=None, actor=ACTOR)
    kwargs.update(overrides)
    return advance(pursuit, **kwargs)


def _last_footer(pursuit):
    runs = sorted((pursuit.root / "runs").glob("*/run.jsonl"))
    return read_run(runs[-1])[-1]


def test_no_gate1_decider_stops_awaiting_gate_and_resumes(tmp_path):
    pursuit = PursuitDir(tmp_path, "pur_demo")
    adv = _advance(pursuit, decide_gate1=None)
    assert (adv.status, adv.stopped_at) == ("awaiting_gate", "gate_1")
    assert adv.ran_stages[-1] == "win_themes"
    footer = _last_footer(pursuit)
    assert footer["record_type"] == "run_end"
    assert footer["run"]["status"] == "awaiting_gate"  # the first writer
    assert not (pursuit.root / "brief.frozen.json").exists()
    # Supplying the decision resumes: checkpointed stages skip, the gate
    # approves, and the pipeline runs on to the next stop.
    adv2 = _advance(pursuit)
    assert (adv2.status, adv2.stopped_at) == ("awaiting_gate", "gate_2")
    assert (pursuit.root / "brief.frozen.json").exists()


def test_no_gate2_decider_stops_with_pending_plan(tmp_path):
    pursuit = PursuitDir(tmp_path, "pur_demo")
    adv = _advance(pursuit)
    assert (adv.status, adv.stopped_at) == ("awaiting_gate", "gate_2")
    assert adv.ran_stages[-1] == "planning"
    assert _last_footer(pursuit)["run"]["status"] == "awaiting_gate"
    plan = pursuit.read_artifact("plan.json")
    assert plan["status"] == "gate2_pending"
    assert not (pursuit.root / "plan.frozen.json").exists()


def test_open_gaps_end_the_drafting_run_awaiting_gap(tmp_path):
    """D15's other half: Gate 2 approved WITHOUT disposing the demo
    package's gaps -> drafting pends those sections -> the run's footer
    says what it honestly is. Non-vacuity twin: the slice's flag-all
    policy on the same package completes (tests/slice)."""
    pursuit = PursuitDir(tmp_path, "pur_demo")
    adv = _advance(pursuit,
                   decide_gate2=lambda p: {"decision": "approved"})
    assert (adv.status, adv.stopped_at) == ("awaiting_gap", "drafting")
    assert adv.problems and "await gap disposition" in adv.problems[0]
    assert _last_footer(pursuit)["run"]["status"] == "awaiting_gap"
    # the stop is real: validation never ran, no annotated draft exists
    assert not (pursuit.root / "drafts" / "annotated-draft.json").exists()
    envelope = pursuit.read_artifact("drafts/draft.json")
    awaiting_slots = [a for s in envelope["sections"]
                      for a in s.get("answers", [])
                      if a.get("status") == "awaiting_disposition"]
    assert awaiting_slots  # the demo package really carries undisposed gaps
    # The frozen plan still holds the open gaps the J1 policy would have
    # flagged — the two paths differ only in the human's answer.
    assert _canned_dispositions(pursuit)


def test_no_gate0_decider_stops_inside_the_intake_run_spending_nothing(
        tmp_path):
    """P15's acceptance guard: with no gate_0 decision the driver stops
    INSIDE the intake run (frozen numbering holds — no new run in the
    chain) and NOTHING past bid_brief spends: zero agent_call lines from
    any later stage, research untouched."""
    pursuit = PursuitDir(tmp_path, "pur_demo")
    adv = _advance(pursuit, decide_gate0=None)
    assert (adv.status, adv.stopped_at) == ("awaiting_gate", "gate_0")
    assert adv.ran_stages == ["intake"]

    runs = sorted((pursuit.root / "runs").glob("*/run.jsonl"))
    assert [r.parent.name for r in runs] == ["run_0001"]  # ONE run only
    records = read_run(runs[0])
    assert records[-1]["run"]["status"] == "awaiting_gate"
    stages_with_calls = {r.get("stage") for r in records
                         if r["record_type"] == "agent_call"}
    assert stages_with_calls <= {"intake", "bid_brief"}, (
        "a stage past intake spent before the human saw the brief")
    assert not (pursuit.root / "brief.frozen.json").exists()

    # resume with a decision: the mini-run hosts it, then the chain runs on
    adv2 = _advance(pursuit, decide_gate1=None)
    assert (adv2.status, adv2.stopped_at) == ("awaiting_gate", "gate_1")
    assert adv2.ran_stages[0] == "gate_0"
    gate_run = read_run(sorted(
        (pursuit.root / "runs").glob("*/run.jsonl"))[1])
    gates = [r["gate"] for r in gate_run if r["record_type"] == "gate"]
    assert gates and gates[0]["which"] == "gate_0_intake"


def test_gate0_rejection_is_the_redo_door(tmp_path):
    """Rejection clears the intake checkpoints and stops the advance —
    the next advance re-runs intake against the fixed inbox rather than
    researching a brief the human just sent back."""
    pursuit = PursuitDir(tmp_path, "pur_demo")
    adv = _advance(pursuit, decide_gate0=lambda p: {
        "decision": "rejected", "notes": "wrong workbook uploaded"})
    assert (adv.status, adv.stopped_at) == ("refused", "gate_0")
    assert "redo door" in adv.problems[0]
    assert "bid_brief" not in pursuit.completed_stages()
    assert "gate_0" not in pursuit.completed_stages()
    assert (pursuit.root / "brief.json").exists()  # kept, not destroyed

    adv2 = _advance(pursuit, decide_gate1=None)
    assert adv2.ran_stages[0] == "intake"  # intake genuinely re-ran
    assert (adv2.status, adv2.stopped_at) == ("awaiting_gate", "gate_1")



def test_driver_stops_on_research_and_win_themes_refusal(tmp_path, monkeypatch):
    """P1-12: in the Gate-1 crash window (brief approved, freeze missing)
    the driver used to re-run research over the approved brief and drop
    win_themes' refusal on the floor. Now the first refusal ends the
    advance and the brief is byte-identical after."""
    pursuit = PursuitDir(tmp_path, "pur_demo")
    adv = _advance(pursuit)
    assert (adv.status, adv.stopped_at) == ("awaiting_gate", "gate_2")
    (pursuit.root / "brief.frozen.json").unlink()
    (pursuit.root / "checkpoints" / "gate_1.json").unlink()
    before = (pursuit.root / "brief.json").read_bytes()
    adv2 = _advance(pursuit, decide_gate1=None)
    assert (adv2.status, adv2.stopped_at) == ("failed", "research")
    assert adv2.problems == ["research refused"]
    assert (pursuit.root / "brief.json").read_bytes() == before
    # the win_themes refusal is honored too (research stubbed complete)
    import engine.pipeline.driver as driver_mod
    from engine.research.findings import ResearchReport
    monkeypatch.setattr(driver_mod, "run_research",
                        lambda *a, **k: ResearchReport(pursuit_id="pur_demo"))
    adv3 = _advance(pursuit, decide_gate1=None)
    assert (adv3.status, adv3.stopped_at) == ("failed", "win_themes")
    assert (pursuit.root / "brief.json").read_bytes() == before


def test_crash_between_plan_write_and_freeze_keeps_dispositions(tmp_path):
    """P0-17: after a crash between the Gate-2 plan write and its freeze,
    `advance` used to re-enter planning and rewrite plan.json from the
    pre-gate checkpoint — dispositions, waives and stamp gone, no error.
    Now planning refuses, plan.json is byte-identical, and the human's
    same-decision resubmit under a fresh clock completes the gate with a
    freeze byte-equal to the one the crash lost. The crash is staged at
    the gate itself: nothing later has run, exactly the real window."""
    from engine.llm import effective_config
    from engine.planning import approve_gate2
    from engine.runlog import RunLogger
    from engine.version import engine_version

    def gate_log():
        log = RunLogger(pursuit.root, pursuit.new_run_id(),
                        pursuit.pursuit_id)
        log.run_start(mode="dry_run", engine_version=engine_version(),
                      config=effective_config(), kb_snapshot="kb@empty")
        return log

    pursuit = PursuitDir(tmp_path, "pur_demo")
    adv = _advance(pursuit)
    assert (adv.status, adv.stopped_at) == ("awaiting_gate", "gate_2")
    log = gate_log()
    approve_gate2(pursuit, log, decision="approved", actor=ACTOR, at=DEFAULT_AT)
    log.run_end(status="completed")
    plan_before = (pursuit.root / "plan.json").read_bytes()
    frozen_before = (pursuit.root / "plan.frozen.json").read_bytes()
    # the crash window: plan stamped approved, freeze and checkpoint gone
    (pursuit.root / "plan.frozen.json").unlink()
    (pursuit.root / "checkpoints" / "gate_2.json").unlink()
    adv2 = _advance(pursuit, decide_gate2=None)
    assert (adv2.status, adv2.stopped_at) == ("failed", "planning")
    assert adv2.problems == ["planning refused"]
    assert (pursuit.root / "plan.json").read_bytes() == plan_before
    # recovery: the SAME decision under a fresh clock
    log = gate_log()
    result = approve_gate2(pursuit, log, decision="approved", actor=ACTOR,
                           at="2026-08-10T09:00:00")
    log.run_end(status="completed")
    assert result.converged is True
    assert (pursuit.root / "plan.frozen.json").read_bytes() == frozen_before
    assert pursuit.checkpoint_payload("gate_2")["at"] == DEFAULT_AT
    assert (pursuit.root / "plan.json").read_bytes() == plan_before
    assert pursuit.read_frozen("pursuit_plan")["status"] == "approved"
    adv3 = _advance(pursuit, decide_gate2=None)
    assert adv3.status == "awaiting_gap" and adv3.stopped_at == "drafting", (
        adv3.status, adv3.stopped_at, adv3.problems)



def test_skip_predicates_verify_bindings_not_existence(tmp_path):
    """P0-16: drafting and validation skip only on a VERIFIED binding —
    a complete envelope bound to the live freeze, an annotated draft
    bound to the live envelope — never on the files merely existing."""
    import json

    from engine.pipeline.driver import draft_is_current, validation_is_current
    from tests.helpers import plant_annotated, plant_freeze
    pursuit = PursuitDir(tmp_path, "pur_pred")
    plan = {"pursuit_id": "pur_pred", "path": "A_designated",
            "sections": [], "status": "approved"}
    pursuit.write_artifact("pursuit_plan", plan)
    _, sha = plant_freeze(pursuit, "pursuit_plan", plan, validate=True)
    draft = pursuit.root / "drafts" / "draft.json"
    assert draft_is_current(pursuit) is False  # nothing drafted
    draft.write_text(json.dumps({"plan_sha256": sha, "revision_n": 0,
                                 "status": "complete", "sections": []}))
    assert draft_is_current(pursuit) is True
    draft.write_text(json.dumps({"plan_sha256": "0" * 64, "revision_n": 0,
                                 "status": "complete", "sections": []}))
    assert draft_is_current(pursuit) is False  # exists, bound elsewhere
    draft.write_text(json.dumps({"plan_sha256": sha, "revision_n": 0,
                                 "status": "in_progress", "sections": []}))
    assert draft_is_current(pursuit) is False
    draft.write_text(json.dumps({"plan_sha256": sha, "revision_n": 0,
                                 "status": "complete", "sections": []}))
    assert validation_is_current(pursuit) is False  # not validated
    plant_annotated(pursuit)
    assert validation_is_current(pursuit) is True
    draft.write_text(json.dumps({"plan_sha256": sha, "revision_n": 1,
                                 "status": "complete", "sections": []}))
    assert validation_is_current(pursuit) is False  # envelope moved on
