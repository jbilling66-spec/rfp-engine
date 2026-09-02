"""Server-computed read models (B37/D3): the server decides status, the
client only renders — "a browser is the easiest place in the system to
grow a second opinion" (v1's most-repeated defect, promoted to a rule).

Every figure here is an artifact-derived FACT, not a metric: stage from
which completed artifacts exist, gap counts from the live plan,
packaging from the annotated draft, cost as the labeled sum of run
totals (`cost_source: "run_totals"` — the metric resolver is P10's,
D29/G14). Three-state discipline: a figure whose source artifact is
absent is ABSENT from the payload, never defaulted — a default here
becomes a claim on screen.
"""

import hashlib
import json
from pathlib import Path

from engine.contracts import ContractError
from engine.runlog import read_run
from engine.workspace.pursuit import latest_run_id_in
from engine.workspace import PursuitDir

_STAGE_ORDER = ("intake", "gate_0", "research", "gate_1", "planning",
                "gate_2", "drafting", "validation")


class _Corrupt(list):
    """Per-row collector: the files a board row could not read (P26a
    Group C, P2-49/M-23) — one corrupt file names itself on ITS row
    instead of 500ing the whole board."""


def _read_json(path: Path, corrupt: list | None = None) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        if corrupt is None:
            raise
        corrupt.append(f"{path.name}: {exc.__class__.__name__} — see the "
                       "recovery runbook")
        return None


def _sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run_totals(root: Path, corrupt: list | None = None) -> dict:
    cost, calls, runs = 0.0, 0, 0
    runs_dir = root / "runs"
    if runs_dir.exists():
        for run_file in sorted(runs_dir.glob("*/run.jsonl")):
            runs += 1
            try:
                records = read_run(run_file)
            except ContractError as exc:
                if corrupt is None:
                    raise
                corrupt.append(f"runs/{run_file.parent.name}: {exc}")
                continue
            for record in records:
                if record.get("record_type") == "agent_call":
                    calls += 1
                    cost += record.get("cost_usd", 0.0)
    return {"cost_usd": round(cost, 6), "agent_calls": calls, "runs": runs,
            "cost_source": "run_totals"}


def _last_run_status(root: Path, corrupt: list | None = None) -> str | None:
    runs_dir = root / "runs"
    run_id = latest_run_id_in(runs_dir)  # M-25: numeric, not lexicographic
    if run_id is None:
        return None
    try:
        records = read_run(runs_dir / run_id / "run.jsonl")
    except ContractError as exc:
        if corrupt is None:
            raise
        corrupt.append(f"runs/{run_id}: {exc}")
        return "corrupt"
    footer = records[-1] if records else None
    if footer and footer.get("record_type") == "run_end":
        return footer["run"]["status"]
    return "in_flight"  # an open run: honest, not a guess


def _stage_and_next(root: Path, brief, plan,
                    corrupt: list | None = None) -> tuple[str, str]:
    """Where the pursuit stands and what a human does next — decided
    HERE, from completed artifacts bound the way the driver binds them
    (P25 item 8's predicates, mirrored in P1-35)."""
    if brief is None:
        return "intake", "upload the RFP package and run intake"
    done = {p.stem for p in (root / "checkpoints").glob("*.json")}
    if "bid_brief" not in done:
        # gate_0's redo door cleared the checkpoints: the brief on disk
        # is the one the human sent back — re-advance re-runs intake
        return "intake", "advance: re-run intake (gate 0 redo)"
    if "gate_0" not in done:
        # P15: the intake review comes first — confirm the engine's
        # reading of the package before research spends anything
        return "gate_0", "decide gate 0 (intake review: assumptions + questions)"
    if not (root / "brief.frozen.json").exists():
        if brief.get("status") == "gate1_pending":
            return "gate_1", "decide Gate 1 (brief + win themes)"
        if brief.get("status") == "declined":
            return "declined", "pursuit declined at Gate 1"
        return "research", "advance: research + win themes"
    if not (root / "plan.frozen.json").exists():
        if plan is not None and plan.get("status") == "gate2_pending":
            return "gate_2", "decide Gate 2 (plan + gap dispositions)"
        return "planning", "advance: build the pursuit plan"
    # P1-35: decided on the HASH BINDINGS the driver decides on (P25 item
    # 8), never on existence — a replanned pursuit's old draft or
    # annotation reads as "draft again" / "validate again", not "review"
    envelope = _read_json(root / "drafts" / "draft.json", corrupt)
    if (envelope is None or envelope.get("status") != "complete"
            or envelope.get("plan_sha256")
            != _sha256(root / "plan.frozen.json")):
        return "drafting", "advance: draft sections"
    annotated = _read_json(root / "drafts" / "annotated-draft.json", corrupt)
    if (annotated is None
            or annotated.get("draft_sha256")
            != _sha256(root / "drafts" / "draft.json")):
        return "validation", "advance: validate the draft"
    if annotated.get("packaging", {}).get("blocked"):
        return "review", "review: packaging BLOCKED on tier-1 claims"
    return "review", "review the annotated draft"


def board(workspace: Path) -> list[dict]:
    rows = []
    workspace = Path(workspace)
    if not workspace.exists():
        return rows
    for root in sorted(p for p in workspace.iterdir() if p.is_dir()):
        if not (root / "brief.json").exists() and not (root / "inbox").exists():
            continue  # not a pursuit workspace (e.g. kb/, support/)
        corrupt = _Corrupt()
        brief = _read_json(root / "brief.json", corrupt)
        plan = _read_json(root / "plan.json", corrupt)
        stage, next_action = _stage_and_next(root, brief, plan, corrupt)
        row = {"pursuit_id": root.name, "stage": stage, "next": next_action,
               "totals": _run_totals(root, corrupt)}
        run_status = _last_run_status(root, corrupt)
        if run_status is not None:
            row["last_run_status"] = run_status
        if plan is not None:
            gaps = [g for s in plan.get("sections", [])
                    for g in s.get("gaps", [])]
            row["open_gaps"] = sum(
                1 for g in gaps if g.get("status") in ("open", "pinged"))
        envelope = _read_json(root / "drafts" / "draft.json", corrupt)
        if envelope is not None:
            row["revision_n"] = envelope.get("revision_n")
        annotated = _read_json(root / "drafts" / "annotated-draft.json",
                               corrupt)
        if annotated is not None and stage == "review":
            # P1-35: packaging is published only when the annotation is
            # CURRENT (the stage says so); a superseded one says nothing
            row["packaging"] = annotated.get("packaging")
        if corrupt:
            row["corrupt"] = list(corrupt)
            row["stage"], row["next"] = "corrupt", (
                "a workspace file is unreadable — see the recovery "
                "runbook: " + "; ".join(corrupt))
        rows.append(row)
    return rows


GUEST_STRIPPED = ("waived_by", "waiver_reason")  # P0-21: never to a guest


def _claim_mark(claim: dict, *, include_internal: bool = True) -> dict:
    """F9 (the owner's J4 ask): a MARK + ONE-LINE reason leads; the full
    forensic row nests under detail, on demand. The artifact itself is
    untouched — this is rendering, never record. The guest rendering
    (include_internal=False) carries neither the waiving operator nor
    the waiver reason ANYWHERE — line or detail (P26a, P0-21: the line
    used to be built before the detail strip)."""
    disposition = claim.get("disposition", "")
    mark = {"block": "block", "flag": "review",
            "waived": "waived"}.get(disposition, "ok")
    line = f"{claim.get('status', '?')}: {claim.get('text', '')[:70]}"
    detail = claim
    if mark == "waived":
        if include_internal:
            line = f"waived by {claim.get('waived_by', '?')}: " \
                   f"{claim.get('text', '')[:60]}"
        else:
            line = f"waived: {claim.get('text', '')[:60]}"
    if not include_internal:
        detail = {k: v for k, v in claim.items() if k not in GUEST_STRIPPED}
        if mark == "waived":
            # the audit trail names the waiver too ("… by <actor> at …")
            # — a guest gets the verdict, never the trail
            detail.pop("reasons", None)
    return {"kind": "claim", "mark": mark, "line": line,
            "claim_id": claim.get("claim_id"),
            "slot_id": claim.get("slot_id"),
            "detail": detail}


def _finding_mark(finding: dict) -> dict:
    return {"kind": "finding", "mark": finding.get("disposition", "review"),
            "line": finding.get("message", ""),
            "check": finding.get("check"),
            "slot_id": finding.get("slot_id"),
            "detail": finding}


def review(workspace: Path, pursuit_id: str, *,
           include_internal: bool = True) -> dict | None:
    """The review surface's render model. include_internal=False is the
    share-view flavor: waiver identities, cost, and pending internals
    are stripped SERVER-side — a guest never receives what the client
    would merely hide."""
    root = Path(workspace) / pursuit_id
    annotated = _read_json(root / "drafts" / "annotated-draft.json")
    envelope = _read_json(root / "drafts" / "draft.json")
    if annotated is None or envelope is None:
        return None
    prose_by_section: dict[str, list[dict]] = {}
    for entry in envelope.get("sections", []):
        slots = [{"slot_id": a.get("slot_id"), "prose": a.get("prose", ""),
                  "status": a.get("status")}
                 for a in entry.get("answers", []) if a.get("prose")]
        if not slots and entry.get("prose"):
            slots = [{"slot_id": None, "prose": entry["prose"],
                      "status": entry.get("status")}]
        prose_by_section[entry["section_id"]] = slots
    pending_by_section: dict[str, list[dict]] = {}
    pending_path = root / "events" / "pending.json"
    if include_internal and pending_path.exists():
        for item in json.loads(
                pending_path.read_text(encoding="utf-8"))["pending"]:
            pending_by_section.setdefault(
                item["section_id"], []).append(item)
    sections = []
    for section in annotated.get("sections", []):
        marks = [_claim_mark(c, include_internal=include_internal)
                 for c in section.get("claims", [])]
        marks += [_finding_mark(f) for f in section.get("findings", [])]
        row = {"section_id": section["section_id"],
               "title": section.get("title", ""),
               "draft_status": section.get("draft_status"),
               "slots": prose_by_section.get(section["section_id"], []),
               "marks": marks}
        if include_internal:
            row["pending"] = pending_by_section.get(
                section["section_id"], [])
            if "red_team" in section:
                row["red_team"] = section["red_team"]
        sections.append(row)
    out = {"pursuit_id": annotated["pursuit_id"],
           "revision_n": annotated.get("revision_n"),
           "validated_at": annotated.get("validated_at"),
           "packaging": annotated.get("packaging"),
           "sections": sections}
    if include_internal:
        out["last_round"] = _last_round(root)
    return out


def _last_round(root: Path) -> dict | None:
    """P27 wave 1: the sections the latest revision round actually
    revised — the ones an accept/reject of the agent's revision applies
    to. Read from `revisions/round_{n}.json` (round.py's record:
    `round_n` + `sections[].outcome`); None until a round has run."""
    rev_dir = root / "revisions"
    rounds = sorted(rev_dir.glob("round_*.json")) if rev_dir.is_dir() else []
    if not rounds:
        return None
    record = _read_json(rounds[-1])
    if record is None:
        return None
    return {"n": record.get("round_n"),
            "revised": sorted(s["section_id"] for s in record.get("sections", [])
                              if s.get("outcome") == "revised")}


def detail(workspace: Path, pursuit_id: str) -> dict | None:
    root = Path(workspace) / pursuit_id
    if not (root / "brief.json").exists() and not (root / "inbox").exists():
        return None  # existence check BEFORE PursuitDir — mkdir side effect
    pursuit = PursuitDir(Path(workspace), pursuit_id)
    brief = _read_json(root / "brief.json")
    plan = _read_json(root / "plan.json")
    stage, next_action = _stage_and_next(root, brief, plan)
    out: dict = {"pursuit_id": pursuit_id, "stage": stage,
                 "next": next_action, "totals": _run_totals(root),
                 "artifacts": sorted(
                     str(p.relative_to(root))
                     for p in root.rglob("*.json") if p.is_file()),
                 "completed_stages": sorted(pursuit.completed_stages())}
    if brief is not None:
        out["brief_status"] = brief.get("status")
        buyer = brief.get("buyer", {})
        if buyer.get("name"):
            out["buyer_name"] = buyer["name"]
    if plan is not None:
        out["plan_status"] = plan.get("status")
        out["sections"] = [
            {"section_id": s["section_id"], "title": s["title"],
             **({"draft_status": s["draft_status"]}
                if "draft_status" in s else {}),
             "gaps": [{k: g[k] for k in
                       ("gap_id", "slot_id", "kind", "status",
                        "question_to_human") if k in g}
                      for g in s.get("gaps", [])]}
            for s in plan.get("sections", [])]
        out["obligations"] = plan.get("obligations", [])
    annotated = _read_json(root / "drafts" / "annotated-draft.json")
    if annotated is not None:
        out["packaging"] = annotated.get("packaging")
        out["revision_n"] = annotated.get("revision_n")
    out["finishing"] = _finishing(pursuit, root, annotated is not None)
    return out


def _finishing(pursuit, root: Path, reviewable: bool) -> dict:
    """P27 wave 1: the preconditions the finish panel's buttons key on
    — named by the SERVER so the shell never infers them. `reviewable`
    = a validated annotated draft exists (the export door's own gate);
    `bundle` = the submission bundle's summary, if ever composed;
    `hand_fill_lane` = the frozen plan's container is the firm-default
    template, the one lane with a hand-completion record."""
    bundle_path = root / "exports" / "submission-bundle.json"
    bundle = _read_json(bundle_path) if bundle_path.is_file() else None
    summary = None
    if bundle is not None:
        rows = bundle.get("deliverables", [])
        summary = {"composed_at": bundle.get("composed_at"),
                   "composed_by": bundle.get("composed_by"),
                   "produced": sum(1 for d in rows
                                   if d.get("status") == "produced"),
                   "refused": sum(1 for d in rows
                                  if d.get("status") == "refused")}
    hand_fill_lane = False
    try:
        frozen = pursuit.read_frozen("pursuit_plan")
        container = pursuit.read_artifact(
            frozen.get("slots_ref", "slots.json"))
        hand_fill_lane = container.get("source_mode") == "firm_default"
    except (FileNotFoundError, KeyError, ValueError, OSError):
        hand_fill_lane = False
    return {"reviewable": reviewable, "bundle": summary,
            "hand_fill_lane": hand_fill_lane}
