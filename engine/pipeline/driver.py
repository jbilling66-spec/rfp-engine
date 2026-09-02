"""The ONE stage-order authority (B37/D26) — extracted from the slice
runner so the web advance job and `make slice` can never drift apart.

Fixed stage order, one run per stage (the fixture chains' convention —
frozen tests pin run numbering): intake -> research -> win_themes+gate_1
-> planning+gate_2 -> drafting -> validation. Stage skip predicates are
the stages' own COMPLETED artifacts (brief.frozen.json, plan.frozen.json,
complete draft envelope, the annotated draft) — never a partially-run
stage's checkpoint (P7 lesson); drafting and validation resume through
their own per-section checkpoints. Research NEVER re-runs once
brief.frozen.json exists — the driver owns stage ordering and closes
B22(9)'s post-gate rerun hazard with the plan_frozen refusal pattern.

Gate stops (D15, the first writers of the dormant run statuses): a
caller that supplies no decision for a gate gets the honest stop — the
stage's work is logged, the run ends `awaiting_gate`, and the driver
returns without touching later stages. A drafting run whose envelope
still carries awaiting_disposition sections ends `awaiting_gap`: the
run is genuinely waiting on humans, and "completed" would lie.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

from engine.drafting import run_drafting
from engine.intake.brief import run_intake
from engine.intake.gate import approve_gate0
from engine.kb import KBStore, Lanes
from engine.kb.pursuit_memory import (
    deposit_supplemental,
    memory_snapshot,
    memory_store,
)
from engine.llm import effective_config
from engine.planning import approve_gate2, run_planning
from engine.workspace import orgs
from engine.research.findings import run_research
from engine.runlog import RunLogger
from engine.strategy.gate import approve_gate1
from engine.strategy.themes import run_win_themes
from engine.validation import run_validation
from engine.version import engine_version


@dataclass
class AdvanceResult:
    status: str = "ok"  # ok | failed | refused | awaiting_gate | awaiting_gap
    stopped_at: str | None = None
    problems: list[str] = field(default_factory=list)
    ran_stages: list[str] = field(default_factory=list)


# P17/C4 (B75§1c): the stages whose retrieval universe the pursuit lane
# joins. Validation is DELIBERATELY absent — the claim audit grounds
# against the firm fact catalog alone, so it receives the plain store.
_LANE_STAGES = frozenset({"research", "planning", "drafting"})

# P17/C6 (B75§1c, the owner's call): org memory is STRATEGY-SIDE ONLY — it
# joins research, never the mapper's grounding searches and never
# drafting, so firm opinion about a buyer can neither flip a slot's
# grounded/gapped verdict nor be cited in prose. Widening this set is a
# deliberate, recorded step (and the funded re-measure must model it).
_ORG_LANE_STAGES = frozenset({"research"})


def _linked_org_id(pursuit) -> str | None:
    try:
        brief = pursuit.read_artifact("brief.json")
    except FileNotFoundError:
        return None
    return brief.get("buyer", {}).get("org_id")


class StageRun:
    """One run per stage: opens the log, wraps the caller, closes the
    footer even when the stage raises mid-flight? No — deliberately NOT:
    a killed stage leaves the honest no-footer log (the fixtures'
    convention); only normal completion writes run_end.

    P17/C4: `lanes` is the retrieval universe for this stage — the Lanes
    bundle when the pursuit has memory and the stage is a lane stage,
    else the plain firm store (byte-identical pre-P17 behavior). The
    run_start header carries pursuit_kb_snapshot exactly when the lane
    can join this run, so the header never claims a universe the run
    does not search."""

    def __init__(self, pursuit, make_caller, mode, stage, *, kb_root,
                 extras=None):
        self.store = KBStore(kb_root)
        self.log = RunLogger(pursuit.root, pursuit.new_run_id(),
                             pursuit.pursuit_id)
        self.caller = make_caller(self.log)
        extra = extras(stage) if extras else None
        cfg = effective_config(extra=extra or None)
        self.lanes = self.store
        run_fields = {}
        pursuit_lane = None
        memory_snap = memory_snapshot(pursuit.root)
        if memory_snap and stage in _LANE_STAGES:
            pursuit_lane = memory_store(pursuit.root)
            run_fields["pursuit_kb_snapshot"] = memory_snap
        org_lane = org_id = None
        if stage in _ORG_LANE_STAGES:
            linked = _linked_org_id(pursuit)
            if linked:
                org_snap = orgs.org_snapshot(pursuit.root.parent, linked)
                if org_snap:
                    org_lane = orgs.org_store(pursuit.root.parent, linked)
                    org_id = linked
                    run_fields["org_kb_snapshot"] = org_snap
        if pursuit_lane is not None or org_lane is not None:
            self.lanes = Lanes(firm=self.store, pursuit=pursuit_lane,
                               org=org_lane, org_id=org_id)
        self.log.run_start(mode=mode, engine_version=engine_version(),
                           config=cfg, kb_snapshot=self.store.snapshot(),
                           research_mode=cfg["research_mode"], **run_fields)

    def end(self, status: str = "completed"):
        self.log.run_end(status=status)


def _deposit_supplementals(pursuit, log) -> None:
    """P17/C4: supplemental-role inbox documents become the pursuit's
    memory lane, logged into the INTAKE run (the gate_0-in-intake
    precedent — no new run, the frozen numbering holds). Authorship is
    not derivable from the role, so the deposit records third_party —
    the conservative bucket; nothing in this lane grounds Tier-1 claims
    regardless (B75§2). Un-chunkable formats refuse loudly inside the
    door, never silently skip."""
    roles_path = pursuit.root / "inbox" / "roles.json"
    if not roles_path.exists():
        return
    roles = json.loads(roles_path.read_text(encoding="utf-8"))
    for name in sorted(roles):
        if roles[name] == "supplemental":
            deposit_supplemental(pursuit, name, authored_by="third_party",
                                 log=log, stage="intake")


def _draft_awaiting_sections(pursuit) -> list[str]:
    """Sections owing content to an undisposed gap — at either grain: a
    whole section awaiting, or any answer slot inside a drafted section
    (a section drafts around its pends, but the pursuit still owes the
    pended slot to a human decision)."""
    envelope = pursuit.read_artifact("drafts/draft.json")
    return [s["section_id"] for s in envelope.get("sections", [])
            if s.get("status") == "awaiting_disposition"
            or any(a.get("status") == "awaiting_disposition"
                   for a in s.get("answers", []))]


def draft_is_current(pursuit) -> bool:
    """Drafting's skip predicate (P25 item 8, P0-16): a COMPLETE envelope
    bound to the LIVE freeze — never bare existence, so a replanned
    pursuit's old draft can never skip drafting."""
    if not (pursuit.root / "drafts" / "draft.json").exists():
        return False
    envelope = pursuit.read_artifact("drafts/draft.json")
    return (envelope.get("status") == "complete"
            and envelope.get("plan_sha256")
            == pursuit.file_sha256("plan.frozen.json"))


def validation_is_current(pursuit) -> bool:
    """Validation's skip predicate (P25 item 8, P0-16): an annotated draft
    bound to the LIVE envelope, which is itself bound to the LIVE freeze."""
    if not (pursuit.root / "drafts" / "annotated-draft.json").exists():
        return False
    annotated = pursuit.read_artifact("drafts/annotated-draft.json")
    return (annotated.get("draft_sha256")
            == pursuit.file_sha256("drafts/draft.json")
            and annotated.get("plan_sha256")
            == pursuit.file_sha256("plan.frozen.json"))


def advance(pursuit, *, make_caller, mode, kb_root, at,
            extras=None, intake_package=None, research_pack=None,
            workbook=None, targets=None, core_doc=None,
            decide_gate0=None, decide_gate1=None,
            decide_gate2=None,
            extraction=None, actor: str = "pipeline") -> AdvanceResult:
    """Run the pipeline forward from wherever the artifacts say it
    stands. Gate deciders are callables(pursuit) -> kwargs for the
    approve_* contracts; None means "no decision available": the driver
    stops there with an `awaiting_gate` footer instead of guessing."""
    result = AdvanceResult()
    root = pursuit.root

    def _gate0_outcome(outcome):
        """Shared post-decision handling: a rejection is the redo door —
        the cleared checkpoints make the next advance re-run intake, and
        this advance stops honestly rather than researching a brief the
        human just sent back."""
        result.ran_stages.append("gate_0")
        if outcome.decision == "rejected":
            result.status = "refused"
            result.stopped_at = "gate_0"
            result.problems.append("gate_0 rejected — fix the package and "
                                   "re-advance (redo door)")
            return True
        return False

    # The intake predicate is the CHECKPOINT, not the artifact (P15): a
    # gate_0 rejection clears the checkpoints while brief.json remains,
    # and the redo must re-run intake against the fixed inbox.
    if "bid_brief" not in pursuit.completed_stages():
        if intake_package is None:
            result.status = "refused"
            result.stopped_at = "intake"
            result.problems.append("no intake package supplied and no "
                                   "brief checkpoint exists — nothing to "
                                   "advance")
            return result
        stage = StageRun(pursuit, make_caller, mode, "intake",
                         kb_root=kb_root, extras=extras)
        report = run_intake(pursuit, stage.caller, stage.log,
                            intake_package(pursuit), extraction=extraction)
        if report.status == "refused":
            stage.end()
            result.status = "failed"
            result.stopped_at = "intake"
            result.problems.append("intake refused")
            return result
        result.ran_stages.append("intake")
        _deposit_supplementals(pursuit, stage.log)
        # gate_0 (P15/B70): the in-chain decision logs into THIS run —
        # no new run in the chain, so the frozen run numbering holds —
        # and the stop reuses this run's awaiting_gate footer.
        if decide_gate0 is None:
            stage.end(status="awaiting_gate")
            result.status = "awaiting_gate"
            result.stopped_at = "gate_0"
            return result
        outcome = approve_gate0(pursuit, stage.log, actor=actor, at=at,
                                kb_root=kb_root, **decide_gate0(pursuit))
        stage.end()
        if _gate0_outcome(outcome):
            return result
    elif "gate_0" not in pursuit.completed_stages():
        # resume-after-stop: the brief exists and its awaiting_gate
        # footer was already written — with no decision there is nothing
        # to log, and with one the decision gets its own mini-run.
        if decide_gate0 is None:
            result.status = "awaiting_gate"
            result.stopped_at = "gate_0"
            result.problems.append("brief awaits the gate_0 decision")
            return result
        stage = StageRun(pursuit, make_caller, mode, "gate_0",
                         kb_root=kb_root, extras=extras)
        outcome = approve_gate0(pursuit, stage.log, actor=actor, at=at,
                                kb_root=kb_root, **decide_gate0(pursuit))
        stage.end()
        if _gate0_outcome(outcome):
            return result

    frozen_brief = root / "brief.frozen.json"
    if not frozen_brief.exists():
        # Research runs at most once, strictly pre-gate. Once the freeze
        # exists this whole block is unreachable — B22(9), closed here.
        stage = StageRun(pursuit, make_caller, mode, "research",
                         kb_root=kb_root, extras=extras)
        pack_path = None
        if research_pack is not None:
            pack_path = root / "inbox" / research_pack.name
            if pack_path != research_pack:
                pack_path.write_bytes(research_pack.read_bytes())
        cfg_mode = effective_config()["research_mode"]
        research = run_research(pursuit, stage.caller, stage.log, stage.lanes,
                                mode=cfg_mode, pack=pack_path)
        if research.status == "refused":
            # P25 item 1 (P1-12): every stage refusal ends the advance —
            # a dropped return used to let the chain walk past it.
            stage.end()
            result.status = "failed"
            result.stopped_at = "research"
            result.problems.append("research refused")
            return result
        stage.end()
        result.ran_stages.append("research")

        stage = StageRun(pursuit, make_caller, mode, "strategy",
                         kb_root=kb_root, extras=extras)
        themes = run_win_themes(pursuit, stage.caller, stage.log)
        if themes.status == "refused":
            stage.end()
            result.status = "failed"
            result.stopped_at = "win_themes"
            result.problems.append("win_themes refused")
            return result
        if decide_gate1 is None:
            stage.end(status="awaiting_gate")
            result.status = "awaiting_gate"
            result.stopped_at = "gate_1"
            result.ran_stages.append("win_themes")
            return result
        approve_gate1(pursuit, stage.log, actor=actor, at=at,
                      **decide_gate1(pursuit))
        stage.end()
        result.ran_stages.append("win_themes+gate_1")

    if not (root / "plan.frozen.json").exists():
        stage = StageRun(pursuit, make_caller, mode, "planning",
                         kb_root=kb_root, extras=extras)
        report = run_planning(pursuit, stage.caller, stage.log, stage.lanes,
                              workbook=workbook, targets=targets,
                              core_doc=core_doc)
        if report.status != "complete":
            stage.end()
            result.status = "failed"
            result.stopped_at = "planning"
            result.problems.append(f"planning {report.status}")
            return result
        if decide_gate2 is None:
            stage.end(status="awaiting_gate")
            result.status = "awaiting_gate"
            result.stopped_at = "gate_2"
            result.ran_stages.append("planning")
            return result
        approve_gate2(pursuit, stage.log, actor=actor, at=at,
                      **decide_gate2(pursuit))
        stage.end()
        result.ran_stages.append("planning+gate_2")

    if not draft_is_current(pursuit):
        stage = StageRun(pursuit, make_caller, mode, "drafting",
                         kb_root=kb_root, extras=extras)
        report = run_drafting(pursuit, stage.caller, stage.log, stage.lanes)
        if report.status == "refused":
            stage.end()
            result.status = "failed"
            result.stopped_at = "drafting"
            result.problems.append("drafting refused")
            return result
        awaiting = _draft_awaiting_sections(pursuit)
        if awaiting:
            # The run genuinely waits on humans (D15): pinged/undisposed
            # gaps left sections awaiting_disposition — "completed" would
            # lie, and the next revise round is what resumes them.
            stage.end(status="awaiting_gap")
            result.status = "awaiting_gap"
            result.stopped_at = "drafting"
            result.problems.append(
                f"{len(awaiting)} section(s) await gap disposition: "
                + ", ".join(awaiting))
            result.ran_stages.append("drafting")
            return result
        stage.end()
        result.ran_stages.append("drafting")

    if not validation_is_current(pursuit):
        stage = StageRun(pursuit, make_caller, mode, "validation",
                         kb_root=kb_root, extras=extras)
        report = run_validation(pursuit, stage.caller, stage.log, stage.store,
                                at=at)
        stage.end()
        if report.status == "refused":
            result.status = "failed"
            result.stopped_at = "validation"
            result.problems.append("validation refused")
            return result
        result.ran_stages.append("validation")

    return result
