"""Gate 2 (Plan) — the headless B5 contract, mirroring Gate 1's
skeleton (engine/strategy/gate.py) with the P6 deltas:

- Edits carry three operation families, all raise-never-drop:
  `dispose` (B24's four-option menu: answered / omit_approved / reframed
  / draft_flagged, addressed by section_id + gap_id; `reframed`
  code-forces mandatory_review — never preselected, always reviewed);
  `sections` (P9/D25: Path B add/kill/edit, Path A title-edit ONLY — a
  killed Path-A section would orphan slots, so Path-A content removal is
  the omission-disposition lane. A human-ADDED section carries a
  code-forced open needs_sme gap: the KB was never searched for it, so
  drafting it undisposed would be invention — the same edits batch may
  dispose it); `waive_obligations` (note required; waived is NOT covered
  and the recount keeps them apart).
  Section edits apply FIRST, then dispositions, then waives.
- Rejection = REDO WITH MANDATORY FEEDBACK (recorded decision, 2026-08-02): notes are
  required, the plan returns to "draft" (DECISION_TO_STATUS_2 — the
  plan vocabulary has no declined; Gate 1 already decided bid/no-bid),
  the planning checkpoints are cleared so the replan genuinely reruns,
  and the gate_2 checkpoint carries the feedback into it. The next
  decision overwrites that checkpoint.
- Approval freezes plan.frozen.json (byte-equal by construction — T6:
  write-back may only touch what the pursuit plan names) and stamps
  created/gate2 with the injected `at` (B19(8)/B22(8): no wall clock).

Write order on approval: plan -> freeze -> log -> checkpoint (B22(10));
a crash between the gate line and the checkpoint may leave one
duplicate gate line on resume — the log is append-only and honest.
"""

import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from engine.contracts import ContractError

FROZEN_PLAN = "plan.frozen.json"

DECISIONS = ("approved", "approved_with_edits", "rejected", "auto_approved")

# B7-class vocabulary split, pinned (B28): rejection returns the plan to
# draft — a redo door, not a terminal state.
DECISION_TO_STATUS_2 = {
    "approved": "approved",
    "approved_with_edits": "approved",
    "auto_approved": "approved",
    "rejected": "draft",
}

_ACTIONS = ("answered", "omit_approved", "reframed", "draft_flagged")

_PLANNING_STAGES = ("path_a_map", "path_b_outline", "pursuit_plan")


@dataclass
class Gate2Result:
    decision: str
    plan_path: Path
    frozen_path: Path | None
    plan_sha256: str
    converged: bool = False


def _summary(edits: dict | None) -> str | None:
    if not edits:
        return None
    parts = []
    if edits.get("dispose"):
        parts.append(f"dispose:{len(edits['dispose'])}")
    ops = [e.get("op") for e in edits.get("sections", [])]
    for op in ("add", "kill", "edit"):
        if op in ops:
            parts.append(f"{op}:{ops.count(op)}")
    if edits.get("waive_obligations"):
        parts.append(f"waive:{len(edits['waive_obligations'])}")
    return " ".join(parts) or None


def _gate2_gap_ping(title: str, actor: str) -> str:
    return (f"[{title} / gate2-added] Section added by {actor} at Gate 2.\n"
            "The knowledge base was not searched for it — provide content "
            "direction, approve omission, or choose flagged drafting (the "
            "engine will not draft around it).")


def _apply_section_edits(pursuit_id: str, plan: dict, edits: dict,
                         actor: str) -> tuple[list[dict], list[tuple]]:
    """Path B add/kill/edit; Path A title-edit only (D25). Returns
    (kill records for the gate_2 checkpoint, gap lines to emit) — gap
    lines are emitted by the caller only after the WHOLE edits batch
    applies, so a failing sibling instruction cannot leave a gap line
    for a section that never landed."""
    from engine.planning.sections import unique_slugs

    path_a = plan.get("path") == "A_designated"
    sections = plan.get("sections", [])
    kills: list[dict] = []
    gap_lines: list[tuple] = []
    gate_gaps = sum(1 for s in sections for g in s.get("gaps", [])
                    if "_gate2_" in g.get("gap_id", ""))
    for entry in edits.get("sections", []):
        if not isinstance(entry, dict) or entry.get("op") not in (
                "add", "kill", "edit"):
            raise ContractError(
                "gate_2 sections: each entry needs op add|kill|edit")
        op = entry["op"]
        if op == "edit":
            extra = set(entry) - {"op", "section_id", "title"}
            if extra:
                raise ContractError(
                    f"gate_2 sections.edit: unknown keys {sorted(extra)}")
            if not entry.get("title"):
                raise ContractError("gate_2 sections.edit: a title is the "
                                    "only editable field and it is missing")
            section = next((s for s in sections
                            if s["section_id"] == entry.get("section_id")),
                           None)
            if section is None:
                raise ContractError(f"gate_2 sections.edit: unknown section "
                                    f"{entry.get('section_id')!r}")
            section["title"] = entry["title"]
        elif path_a:
            raise ContractError(
                f"gate_2 sections.{op}: Path A sections mirror the buyer's "
                "designated structure — title edits only; content removal "
                "is the omission-disposition lane (D25)")
        elif op == "kill":
            extra = set(entry) - {"op", "section_id", "reason"}
            if extra:
                raise ContractError(
                    f"gate_2 sections.kill: unknown keys {sorted(extra)}")
            if not entry.get("reason"):
                raise ContractError(
                    "gate_2 sections.kill: a reason is required")
            section = next((s for s in sections
                            if s["section_id"] == entry.get("section_id")),
                           None)
            if section is None:
                raise ContractError(f"gate_2 sections.kill: unknown section "
                                    f"{entry.get('section_id')!r}")
            sections.remove(section)
            kills.append({"section_id": section["section_id"],
                          "title": section["title"],
                          "reason": entry["reason"], "by": actor})
        else:  # add
            extra = set(entry) - {"op", "title"}
            if extra:
                raise ContractError(
                    f"gate_2 sections.add: unknown keys {sorted(extra)}")
            if not entry.get("title"):
                raise ContractError("gate_2 sections.add: a title is required")
            existing = [s["section_id"] for s in sections]
            slug = unique_slugs(existing + [entry["title"]])[-1]
            gate_gaps += 1
            gap_id = f"gap_{pursuit_id}_gate2_{gate_gaps:02d}"
            ping = _gate2_gap_ping(entry["title"], actor)
            # No source field: absence means the section answers neither
            # the buyer's structure nor the architect — it was added here.
            sections.append({
                "section_id": slug,
                "title": entry["title"],
                "gaps": [{
                    "gap_id": gap_id,
                    "kind": "needs_sme",
                    "question_to_human": ping,
                    "status": "open",
                }],
            })
            gap_lines.append(({"section_id": slug}, {
                "gap_id": gap_id,
                "reason": "needs_sme",
                "question_to_human": ping,
                "resolution": "unresolved",
            }))
    return kills, gap_lines


def _apply_waives(plan: dict, edits: dict) -> None:
    """Obligation waives (D25): note required; only a gapped obligation
    can be waived — covered needs no waiver, waived twice is a conflict.
    Waived stays distinct from covered everywhere downstream."""
    rows = {o["id"]: o for o in plan.get("obligations", [])}
    for entry in edits.get("waive_obligations", []):
        if not isinstance(entry, dict) or not entry.get("id"):
            raise ContractError(
                "gate_2 waive_obligations: each entry needs an id")
        extra = set(entry) - {"id", "note"}
        if extra:
            raise ContractError(
                f"gate_2 waive_obligations: unknown keys {sorted(extra)}")
        if not entry.get("note"):
            raise ContractError(
                f"gate_2 waive_obligations: {entry['id']} requires a note "
                "— the reason is the record")
        row = rows.get(entry["id"])
        if row is None:
            raise ContractError(
                f"gate_2 waive_obligations: unknown obligation "
                f"{entry['id']!r}")
        if row["status"] == "waived":
            raise ContractError(
                f"gate_2 waive_obligations: {entry['id']} is already waived")
        if row["status"] != "gapped":
            raise ContractError(
                f"gate_2 waive_obligations: {entry['id']} is "
                f"{row['status']!r} — only a gapped obligation is waivable")
        row["status"] = "waived"
        row["note"] = entry["note"]


def _apply_dispositions(plan: dict, edits: dict) -> None:
    """Human gap dispositions, raise-never-drop (B22(11) discipline: a
    failed human instruction is never silently ignored)."""
    unknown = set(edits) - {"dispose", "sections", "waive_obligations"}
    if unknown:
        raise ContractError(f"gate_2 edits: unknown operations {sorted(unknown)}")
    sections = {s["section_id"]: s for s in plan.get("sections", [])}
    for item in edits.get("dispose", []):
        section = sections.get(item.get("section_id"))
        if section is None:
            raise ContractError(
                f"gate_2 dispose: unknown section {item.get('section_id')!r}"
            )
        gap = next((g for g in section.get("gaps", [])
                    if g.get("gap_id") == item.get("gap_id")), None)
        if gap is None:
            raise ContractError(
                f"gate_2 dispose: no gap {item.get('gap_id')!r} in "
                f"{item['section_id']!r}"
            )
        action = item.get("action")
        if action not in _ACTIONS:
            raise ContractError(f"gate_2 dispose: unknown action {action!r}")
        if gap.get("status") != "open":
            raise ContractError(
                f"gate_2 dispose: gap {gap['gap_id']} is already "
                f"{gap.get('status')!r}, not open"
            )
        if action == "answered":
            if not item.get("answer"):
                raise ContractError(
                    f"gate_2 dispose: answered {gap['gap_id']} requires an "
                    "answer"
                )
            gap["answer"] = item["answer"]
        elif action == "reframed":
            if not item.get("note"):
                raise ContractError(
                    f"gate_2 dispose: reframed {gap['gap_id']} requires a "
                    "note (the reframe direction)"
                )
            # mandatory_review is code-forced — the human cannot unset it
            # (B24: a reframe is never preselected and always reviewed).
            gap["reframe"] = {"note": item["note"], "mandatory_review": True}
        elif action == "draft_flagged":
            if item.get("answer"):
                raise ContractError(
                    f"gate_2 dispose: draft_flagged {gap['gap_id']} takes no "
                    "answer — it authorizes flagged drafting, not content"
                )
        if action != "reframed" and item.get("note"):
            gap["note"] = item["note"]
        gap["status"] = action


def _recount_coverage(plan: dict) -> None:
    """Recompute the disposition buckets. Path-A identity: covered =
    total - open - omit - draft (reframed and answered count covered).
    Path B recomputes its refs-based covered from the CURRENT sections
    (B28's formula, re-run so a Gate-2 section kill cannot leave a stale
    figure). Waived obligations live on the obligations rows, never in
    these buckets — waived is not covered (D25)."""
    cov = plan.get("coverage_summary", {})
    statuses = [g["status"] for s in plan.get("sections", [])
                for g in s.get("gaps", [])]
    cov["open_gaps"] = sum(1 for s in statuses if s in ("open", "pinged"))
    cov["omit_approved"] = sum(1 for s in statuses if s == "omit_approved")
    cov["draft_flagged"] = sum(1 for s in statuses if s == "draft_flagged")
    if plan.get("path") == "A_designated":
        cov["covered"] = (cov.get("total_requirements", 0) - cov["open_gaps"]
                          - cov["omit_approved"] - cov["draft_flagged"])
    else:
        cov["covered"] = len({ref for s in plan.get("sections", [])
                              for ref in s.get("requirement_refs", [])})
    plan["coverage_summary"] = cov


def approve_gate2(pursuit, log, *, decision: str, actor: str, at: str,
                  notes: str | None = None, edits: dict | None = None,
                  wait_ms: int = 0, auto_approved: bool = False,
                  gates_collapsed: bool = False) -> Gate2Result:
    # --- validation, all before any write (gate.py order) ---------------
    if decision not in DECISIONS:
        raise ContractError(
            f"gate_2 decision must be one of {DECISIONS}, got {decision!r}"
        )
    if (decision == "auto_approved") != auto_approved:
        raise ContractError(
            "auto_approved is reserved for replay: the flag and decision "
            "must agree (B22(13))"
        )
    if not actor:
        raise ContractError("gate_2 requires an actor")
    try:
        datetime.fromisoformat(at.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        # jsonschema format checking is off — this is the date-time gate.
        raise ValueError(f"gate_2 'at' must be ISO 8601, got {at!r}")
    if decision == "approved_with_edits" and not edits:
        raise ContractError("approved_with_edits requires edits")
    if decision == "rejected":
        if not notes:
            raise ContractError(
                "gate_2 rejection requires notes — feedback is the point "
                "of the redo (recorded decision, 2026-08-02)"
            )
        if edits:
            raise ContractError(
                "gate_2 rejection takes no dispositions — the redo replans"
            )
    try:
        plan = pursuit.read_artifact("plan.json")
    except FileNotFoundError:
        raise ContractError("gate_2: no plan.json — nothing to approve")
    status = DECISION_TO_STATUS_2[decision]
    plan_path = pursuit.root / "plan.json"
    frozen_path = pursuit.root / FROZEN_PLAN

    # --- idempotency / conflict (B22(10), adapted for the redo door) ----
    if "gate_2" in pursuit.completed_stages():
        prior = pursuit.checkpoint_payload("gate_2")
        if (prior.get("decision"), prior.get("actor"), prior.get("at")) == (
            decision, actor, at,
        ):
            return Gate2Result(
                decision=decision, plan_path=plan_path,
                frozen_path=frozen_path if frozen_path.exists() else None,
                plan_sha256=prior.get("plan_sha256", ""), converged=True,
            )
        if plan.get("status") != "gate2_pending":
            raise ContractError(
                f"gate_2 already decided: {prior.get('decision')!r} by "
                f"{prior.get('actor')!r} at {prior.get('at')} — a new "
                "decision needs a replanned plan (gate2_pending)"
            )
        # else: post-redo — the fresh decision overwrites the checkpoint.

    section_kills: list[dict] = []
    stamped_already = False
    if plan.get("status") == "approved" and plan.get("gate2"):
        gate2 = plan["gate2"]
        if (status, gate2.get("approved_by"), gate2.get("at")) != (
            "approved", actor, at,
        ):
            raise ContractError(
                "gate_2: the plan is already past the gate with a different "
                "decision"
            )
        stamped_already = True  # mid-gate crash window: complete convergently
    elif decision == "rejected":
        if plan.get("status") not in ("gate2_pending", "draft"):
            raise ContractError(
                f"gate_2: cannot reject a plan in status "
                f"{plan.get('status')!r}"
            )
    elif plan.get("status") != "gate2_pending":
        raise ContractError(
            f"gate_2 requires a gate2_pending plan, got "
            f"{plan.get('status')!r}"
        )

    log.emit("stage_start", stage="gate_2")

    # --- stamp -----------------------------------------------------------
    if not stamped_already:
        if edits:
            # Section edits first so a same-batch disposition can target
            # an added section's code-forced gap (D25); gap lines land
            # only after the whole batch applies.
            section_kills, gap_lines = _apply_section_edits(
                pursuit.pursuit_id, plan, edits, actor)
            _apply_dispositions(plan, edits)
            _apply_waives(plan, edits)
            for target, gap in gap_lines:
                log.emit("gap", stage="gate_2", gap=gap, target=target)
        _recount_coverage(plan)
        if status == "approved":
            gate2: dict = {"approved_by": actor, "at": at}
            if notes:
                gate2["notes"] = notes
            if gates_collapsed:
                gate2["gates_collapsed"] = True
            plan["gate2"] = gate2
            plan["created"] = at  # the plan's first wall-clock, injected
        plan["status"] = status

    # --- write order: plan -> freeze -> log -> checkpoint ----------------
    plan_path = pursuit.write_artifact("pursuit_plan", plan)
    plan_sha = hashlib.sha256(plan_path.read_bytes()).hexdigest()
    log.emit("artifact", stage="gate_2", artifact={
        "kind": "pursuit_plan", "path": str(plan_path), "sha256": plan_sha,
    })
    frozen_out: Path | None = None
    if status == "approved":
        frozen_out = pursuit.write_artifact("pursuit_plan", plan,
                                            name=FROZEN_PLAN)
        log.emit("artifact", stage="gate_2", artifact={
            "kind": "pursuit_plan",
            "path": str(frozen_out),
            "sha256": hashlib.sha256(frozen_out.read_bytes()).hexdigest(),
        })

    gate_payload = {
        "which": "gate_2_plan",
        "decision": decision,
        "actor": actor,
        "auto_approved": auto_approved,
        "wait_ms": wait_ms,
    }
    summary = _summary(edits)
    if summary:
        gate_payload["edits_summary"] = summary
    log.emit("gate", stage="gate_2", gate=gate_payload)

    if decision == "rejected":
        # The redo door: cleared checkpoints make the replan real; the
        # gate_2 checkpoint outlives them — it carries the feedback.
        for stage in _PLANNING_STAGES:
            pursuit.clear_checkpoint(stage)
        pursuit.checkpoint("gate_2", {
            "decision": decision, "actor": actor, "at": at, "notes": notes,
            "plan_sha256": plan_sha,
        })
    else:
        payload = {
            "decision": decision, "actor": actor, "at": at,
            "plan_sha256": plan_sha,
            "frozen_sha256": (
                hashlib.sha256(frozen_out.read_bytes()).hexdigest()
                if frozen_out else None
            ),
        }
        if section_kills:
            # The kill reasons' durable detail; the gate line carries the
            # count (edits_summary) and the log is append-only.
            payload["section_kills"] = section_kills
        pursuit.checkpoint("gate_2", payload)
    log.emit("stage_end", stage="gate_2")
    return Gate2Result(decision=decision, plan_path=plan_path,
                       frozen_path=frozen_out, plan_sha256=plan_sha)
