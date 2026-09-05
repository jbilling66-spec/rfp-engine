"""run_drafting — the drafting stage (P7, B31): one guarded per-section
loop with a replay-always envelope assembly around it.

Refusal gates before any spend (plan.py pattern). Content authority is
brief.frozen.json + plan.frozen.json (B22(9)/T6); the LIVE plan.json is
touched in exactly one field — sections[].draft_status — the B22(9)
live-copy-vs-record pattern (the frozen copy never changes).

Prepass writes the COMPLETE envelope before the first model call (v1
lesson: a run killed early still names every slot owed, durably, in the
artifact of record), then each completed section checkpoints (N2). The
skip predicate on resume is the checkpoint payload's own per-section
map, NEVER completed_stages() — an accumulating checkpoint makes
stage-file existence lie. Assembly runs the same code at prepass and
close, so fresh and resumed runs are byte-identical.

Execution is sequential (B29(c)(6) single-writer until P9) but the
trace is parallel-shaped from day one: drafting agent_calls carry
span_id/parent_span (first writer, B31(9)) as deterministic strings.

Every drafted section ends with one step:"cite" kb_retrieval line — the
cards_cited carrier WP9's edit_survival join keys on. A section pended
by an unusable wire emits no cite line (nothing was cited; the opens
are already on the trace). CostCeilingExceeded propagates after the
last checkpoint — the run aborts loudly (N6 stays a live control) and
resume completes the remaining sections without respend (B31(10)).
"""

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from engine.contracts import ContractError
from engine.drafting import compose, route, verify, wire
from engine.drafting.compose import VOICE_DEFAULT, load_voice_spec
from engine.kb import UseRestrictedCard, as_lanes, targeted_open
from engine.kb.notes import steward_notes_frame
from engine.kb.retrieve import emit_kb_retrieval
from engine.llm.frames import wrap_kb_card

ROOT = Path(__file__).resolve().parents[2]
_PROMPT = ROOT / "prompts" / "section_drafter" / "prompt.md"

DRAFT_NAME = "drafts/draft.json"
STAGE = "drafting"
AGENT = "section_drafter"
STAGE_SPAN = "stage:drafting"
FROZEN_PLAN = "plan.frozen.json"
FROZEN_BRIEF = "brief.frozen.json"


@dataclass
class DraftReport:
    pursuit_id: str
    status: str = "complete"  # complete | refused
    warnings: list[str] = field(default_factory=list)
    drafted: list[str] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)
    draft_path: Path | None = None


def _refuse(log, report: DraftReport, *, code: str, message: str) -> DraftReport:
    log.emit("error", stage=STAGE, error={
        "code": code,
        "message": message,
        "recoverable": True,
        "action_taken": "surfaced_to_human",
    })
    report.status = "refused"
    return report


def run_drafting(pursuit, caller, log, store, *,
                 voice_path: Path = VOICE_DEFAULT) -> DraftReport:
    report = DraftReport(pursuit_id=pursuit.pursuit_id)

    # --- refusal gates: the fork predicate, zero spend ------------------
    try:
        plan_live = pursuit.read_artifact("plan.json")
    except FileNotFoundError:
        return _refuse(log, report, code="missing_plan",
                       message="no plan.json in the pursuit workspace")
    if plan_live.get("status") != "approved":
        return _refuse(
            log, report, code="plan_not_approved",
            message=f"plan status is {plan_live.get('status')!r} — drafting "
                    "requires a Gate-2-approved plan")
    if not (pursuit.root / FROZEN_PLAN).exists():
        return _refuse(
            log, report, code="missing_frozen_plan",
            message="plan is approved but plan.frozen.json is missing — the "
                    "Gate-2 freeze is the drafting input (T6)")
    if not (pursuit.root / FROZEN_BRIEF).exists():
        return _refuse(
            log, report, code="missing_frozen_brief",
            message="brief.frozen.json is missing — the frozen brief is the "
                    "drafting context (T7/B22(9))")

    try:  # content authority — verified against the gate record (P0-2)
        frozen_plan = pursuit.read_frozen("pursuit_plan")
        frozen_brief = pursuit.read_frozen("bid_brief")
    except ContractError as exc:
        return _refuse(log, report, code="frozen_verification_failed",
                       message=str(exc))
    path = frozen_plan.get("path")
    slots_by_id: dict[str, dict] = {}
    if path == "A_designated":
        slots_ref = frozen_plan.get("slots_ref", "slots.json")
        try:
            container = pursuit.read_artifact(slots_ref)
        except FileNotFoundError:
            return _refuse(
                log, report, code="missing_slots",
                message=f"Path A plan names {slots_ref} and it is missing")
        slots_by_id = {s["slot_id"]: s for s in container["slots"]}

    voice_text = load_voice_spec(voice_path)  # malformed firm config raises
    notes_frame = steward_notes_frame(store)  # P26c: accepted steward notes
    plan_sha256 = pursuit.file_sha256(FROZEN_PLAN)

    # --- routing prepass (pure) -----------------------------------------
    routing: dict[str, dict] = {}
    for section in frozen_plan["sections"]:
        rp = route.section_plan(section, slots_by_id, path)
        texts = [slots_by_id[sid].get("question_text", "")
                 for sid in section.get("slot_ids", []) if sid in slots_by_id]
        rp["section_type"] = route.assign_section_type(section["title"], texts)
        routing[section["section_id"]] = rp
        report.warnings.extend(rp["warnings"])

    log.emit("stage_start", stage=STAGE, span_id=STAGE_SPAN)

    ckpt = (pursuit.checkpoint_payload(STAGE)
            if STAGE in pursuit.completed_stages()
            else {"sections": {}, "complete": False})
    if ckpt.get("plan_sha256") != plan_sha256:
        # P25 item 8 (P0-16): a checkpoint built against ANOTHER freeze
        # (or one that never recorded its binding) is discarded, never
        # resumed — resuming would re-bind the old prose to the new plan
        # hash with zero model calls.
        ckpt = {"sections": {}, "complete": False}
    ckpt["plan_sha256"] = plan_sha256

    # --- prepass: the complete outcome set, durable before any spend ----
    _write_envelope(pursuit, log, frozen_plan, routing, ckpt, plan_sha256,
                    path, slots_by_id, status="in_progress")
    _write_draft_status(pursuit, log, plan_live, routing, ckpt)

    # --- the per-section loop -------------------------------------------
    for section in frozen_plan["sections"]:
        section_id = section["section_id"]
        rp = routing[section_id]
        if rp["status"] != route.MODEL or section_id in ckpt["sections"]:
            continue
        entry = _draft_section(
            pursuit, caller, log, store, section, rp, slots_by_id, path,
            voice_text, frozen_brief,
            frozen_plan.get("effort_allocation", "uniform"),
            notes_frame=notes_frame)
        ckpt["sections"][section_id] = entry
        pursuit.checkpoint(STAGE, ckpt)  # N2: after each completed section

    # --- assembly (replay-always) ---------------------------------------
    ckpt["complete"] = True
    pursuit.checkpoint(STAGE, ckpt)
    draft_path = _write_envelope(pursuit, log, frozen_plan, routing, ckpt,
                                 plan_sha256, path, slots_by_id,
                                 status="complete")
    _write_draft_status(pursuit, log, plan_live, routing, ckpt)
    log.emit("stage_end", stage=STAGE)

    report.draft_path = draft_path
    for section in frozen_plan["sections"]:
        entry = ckpt["sections"].get(section["section_id"])
        if entry is not None and entry["status"] == "drafted":
            report.drafted.append(section["section_id"])
        elif routing[section["section_id"]]["status"] in (route.MODEL,
                                                          route.AWAITING):
            report.pending.append(section["section_id"])
        entry_warnings = (entry or {}).get("warnings", [])
        report.warnings.extend(w for w in entry_warnings
                               if w not in report.warnings)
    return report


# --- the guarded per-section work ---------------------------------------

def _draft_section(pursuit, caller, log, store, section, rp, slots_by_id,
                   path, voice_text, frozen_brief,
                   effort_allocation="uniform", notes_frame: str = "") -> dict:
    section_id = section["section_id"]
    section_type = rp["section_type"]
    target = {"section_id": section_id, "section_type": section_type}
    query = f"plan:{section_id}"
    warnings = list(rp["warnings"])

    # Open exactly the plan's selection (the RAG ban, B31(1)).
    planned_ids = [h["kb_id"] for h in section.get("kb_hits", [])]
    opened: list[str] = []
    restricted: list[str] = []
    card_frames: list[str] = []
    canonical_ids: list[str] = []
    bodies: dict[str, str] = {}
    for kb_id in planned_ids:
        try:
            body = targeted_open(store, kb_id, log=log, stage=STAGE,
                                 agent=AGENT, query=query, target=target)
        except UseRestrictedCard as exc:
            restricted.append(kb_id)
            # D2, or a steward's deprecation (P26c) — withheld either way
            warnings.append(f"{kb_id}: withheld from the prompt at draft "
                            f"time — {exc}")
            continue
        # P17/C4: the card front comes from the lane that minted the id
        # (a Lanes bundle dispatches by prefix; a bare store is itself).
        front, _ = as_lanes(store).store_for(kb_id).read_card(kb_id)
        opened.append(kb_id)
        bodies[kb_id] = body
        card_frames.append(wrap_kb_card(kb_id, front.get("title", ""), body))
        if front.get("canonical_block"):
            canonical_ids.append(kb_id)

    model_lanes = [l for l in rp["lanes"] if l["lane"] == route.MODEL]
    model_slots = [slots_by_id[l["slot_id"]] for l in model_lanes]
    flagged_ids = [l["slot_id"] for l in model_lanes if l.get("flagged")]
    requested = [s["slot_id"] for s in model_slots]

    directive = compose.section_directive(
        section, model_slots, canonical_ids=canonical_ids,
        flagged_slot_ids=flagged_ids, flag_section=rp["flag_section"],
        path=path,
        canonical_bodies={k: bodies[k] for k in canonical_ids},
        effort_allocation=effort_allocation)
    prompt = compose.build_draft_prompt(
        voice_text=voice_text, frozen_brief=frozen_brief,
        model_slots=model_slots, card_frames=card_frames,
        steering=rp["steering"], directive=directive,
        notes_frame=notes_frame)
    system = _PROMPT.read_text(encoding="utf-8")

    result = caller.call(AGENT, tier="mid", prompt=prompt, system=system,
                         stage=STAGE, span_id=f"{section_id}:draft",
                         parent_span=STAGE_SPAN, **target)
    opened_set = set(opened)
    try:
        if path == "A_designated":
            drafted, wire_warnings = wire.parse_wire_answers(
                result.text, requested=requested, opened_ids=opened_set)
        else:
            drafted, wire_warnings = wire.parse_wire_prose(
                result.text, opened_ids=opened_set)
    except wire.WireError as e:
        # The section pends, the run continues (v1: a named pend beats a
        # failed job). Nothing was cited — no cite line.
        warnings.append(f"{section_id}: {e}")
        return _entry(section, rp, slots_by_id, status="pending",
                      reason=str(e), warnings=warnings, path=path)
    warnings.extend(wire_warnings)

    # Self-check: one round, fails open (B31(2)).
    checklist = _checklist(model_slots, canonical_ids, flagged_ids,
                           rp["flag_section"], frozen_brief)
    check_prompt = compose.build_check_prompt(
        section, drafted, checklist=checklist, path=path)
    check = caller.call(AGENT, tier="mid", prompt=check_prompt, system=system,
                        stage=STAGE, span_id=f"{section_id}:check",
                        parent_span=STAGE_SPAN, **target)
    verdict, replacement, check_warnings = wire.parse_wire_check(
        check.text, requested=requested if path == "A_designated" else None,
        opened_ids=opened_set)
    warnings.extend(check_warnings)
    if verdict == "fixed":
        drafted = replacement

    entry = _entry(section, rp, slots_by_id, status="drafted",
                   drafted=drafted, bodies=bodies,
                   canonical_ids=canonical_ids, warnings=warnings, path=path)

    emit_kb_retrieval(
        log, stage=STAGE, agent=AGENT, query=query, step="cite",
        cards_returned=planned_ids, cards_opened=opened,
        cards_cited=entry["cards_cited"], excluded=restricted, target=target)
    return entry


def _checklist(model_slots, canonical_ids, flagged_ids, flag_section,
               frozen_brief) -> list[str]:
    out: list[str] = []
    for slot in model_slots:
        constraints = slot.get("constraints", {})
        if constraints.get("max_words") is not None:
            out.append(f"SLOT {slot['slot_id']}: hard limit "
                       f"{constraints['max_words']} words")
        if constraints.get("max_chars") is not None:
            out.append(f"SLOT {slot['slot_id']}: hard limit "
                       f"{constraints['max_chars']} characters")
    for kb_id in canonical_ids:
        out.append(f"the body of {kb_id} appears verbatim in the answer "
                   "that uses it, cited")
    if flagged_ids or flag_section:
        out.append("every novel claim in flagged drafting carries "
                   "[proposed approach]")
    if frozen_brief.get("buyer", {}).get("terminology"):
        out.append("the buyer's terminology is mirrored where it fits")
    if frozen_brief.get("win_themes", {}).get("approved"):
        out.append("approved win themes are threaded where they are true")
    return out


def _entry(section, rp, slots_by_id, *, status, reason=None, drafted=None,
           bodies=None, canonical_ids=(), warnings=(), path="A_designated"
           ) -> dict:
    """One envelope section entry — the same composer for pends and
    drafts, so the skeleton and the final artifact cannot drift."""
    entry: dict = {
        "section_id": section["section_id"],
        "title": section["title"],
        "section_type": rp["section_type"],
        "status": status,
    }
    if reason:
        entry["reason"] = reason
    entry_warnings = list(warnings)

    if path == "A_designated":
        answers = []
        cited: list[str] = []
        for lane in rp["lanes"]:
            if lane["lane"] == route.SHAPE:
                continue  # no lane owns non-prose at P7 (B28(4))
            slot = slots_by_id[lane["slot_id"]]
            answer: dict = {"slot_id": lane["slot_id"]}
            if slot.get("ref_id"):
                answer["ref_id"] = slot["ref_id"]
            if lane["lane"] == route.MODEL:
                got = (drafted or {}).get(lane["slot_id"])
                if got is not None:
                    answer["status"] = "drafted"
                    answer["prose"] = got["prose"]
                    answer["kb_ids"] = got["kb_ids"]
                    answer["proposed_approach"] = verify.flag_present(
                        got["prose"])
                    cited.extend(k for k in got["kb_ids"] if k not in cited)
                    if lane.get("flagged") and not answer["proposed_approach"]:
                        entry_warnings.append(
                            f"{lane['slot_id']}: draft_flagged but no "
                            "[proposed approach] flag in the drafted text "
                            "(P8 blocks)")
                    entry_warnings.extend(
                        verify.length_warnings(slot, got["prose"]))
                else:
                    answer["status"] = "pending"
                    answer["reason"] = (
                        reason or "no result in the section's wire — "
                        "P9 revision completes it")
            elif lane["lane"] == route.OMITTED:
                answer["status"] = "omitted"
                answer["reason"] = lane.get("reason", "omission approved")
                line = verify.omission_line(slot)
                answer["omission_stated"] = line is not None
                if line is not None:
                    answer["prose"] = line
            elif lane["lane"] == route.GATED:
                answer["status"] = "gated_skipped"
                answer["reason"] = lane.get("reason", "gated")
            else:  # AWAITING
                answer["status"] = "awaiting_disposition"
                answer["reason"] = lane.get("reason", "gap undisposed")
            answers.append(answer)
        entry["answers"] = answers
        if status == "drafted":
            # Section citation union in plan kb_hits order (code-owned).
            planned = [h["kb_id"] for h in section.get("kb_hits", [])]
            entry["cards_cited"] = [k for k in planned if k in cited]
    else:
        if status == "drafted":
            entry["prose"] = drafted["prose"]
            entry["cards_cited"] = drafted["kb_ids"]
            entry["proposed_approach"] = verify.flag_present(drafted["prose"])
            if (rp["flag_section"] and not entry["proposed_approach"]):
                entry_warnings.append(
                    f"{section['section_id']}: flagged drafting but no "
                    "[proposed approach] flag in the drafted text (P8 blocks)")

    if status == "drafted":
        texts = ([a.get("prose", "") for a in entry.get("answers", [])]
                 if path == "A_designated" else [entry.get("prose", "")])
        canonical = []
        for kb_id in canonical_ids:
            verified = any(
                verify.canonical_verified((bodies or {}).get(kb_id, ""), t)
                for t in texts if t)
            canonical.append({"kb_id": kb_id, "verified": verified})
            if not verified:
                entry_warnings.append(
                    f"{kb_id}: canonical block not reproduced near-verbatim "
                    "(recorded finding — P8 formalizes enforcement)")
        if canonical:
            entry["canonical"] = canonical
        if path == "A_designated":
            entry["proposed_approach"] = any(
                a.get("proposed_approach") for a in entry["answers"])
    if entry_warnings:
        entry["warnings"] = entry_warnings
    return entry


# --- the replay-always writes -------------------------------------------

def _write_envelope(pursuit, log, frozen_plan, routing, ckpt, plan_sha256,
                    path, slots_by_id, *, status: str) -> Path:
    sections = []
    for section in frozen_plan["sections"]:
        section_id = section["section_id"]
        done = ckpt["sections"].get(section_id)
        if done is not None:
            sections.append(done)
            continue
        rp = routing[section_id]
        if rp["status"] == route.MODEL:
            entry = _entry(section, rp, slots_by_id, status="pending",
                           reason="not reached — resume completes it",
                           warnings=rp["warnings"], path=path)
        elif rp["status"] == route.OMITTED:
            entry = _entry(section, rp, slots_by_id, status="omitted",
                           reason=rp["reason"], warnings=rp["warnings"],
                           path=path)
        elif rp["status"] == route.AWAITING:
            entry = _entry(section, rp, slots_by_id, status="pending",
                           reason=rp["reason"], warnings=rp["warnings"],
                           path=path)
        else:  # SHAPE
            entry = _entry(section, rp, slots_by_id,
                           status="skipped_non_prose", reason=rp["reason"],
                           warnings=rp["warnings"], path=path)
        sections.append(entry)
    envelope = {
        "pursuit_id": pursuit.pursuit_id,
        "plan_sha256": plan_sha256,
        "revision_n": 0,
        "status": status,
        "sections": sections,
    }
    draft_path = pursuit.write_artifact("draft", envelope, name=DRAFT_NAME)
    log.emit("artifact", stage=STAGE, artifact={
        "kind": "draft",
        "path": str(draft_path),
        "sha256": hashlib.sha256(draft_path.read_bytes()).hexdigest(),
        "revision_n": 0,
    })
    return draft_path


def _write_draft_status(pursuit, log, plan_live, routing, ckpt) -> None:
    """The live plan.json's one drafting-owned field (B31(6)): planned ->
    drafted on draftable sections only; absence elsewhere is honest."""
    for section in plan_live.get("sections", []):
        rp = routing.get(section["section_id"])
        if rp is None or rp["status"] != route.MODEL:
            continue
        done = ckpt["sections"].get(section["section_id"])
        if done is not None and done["status"] == "drafted":
            section["draft_status"] = "drafted"
        else:
            section["draft_status"] = "planned"
    plan_path = pursuit.write_artifact("pursuit_plan", plan_live)
    log.emit("artifact", stage=STAGE, artifact={
        "kind": "pursuit_plan",
        "path": str(plan_path),
        "sha256": hashlib.sha256(plan_path.read_bytes()).hexdigest(),
    })
