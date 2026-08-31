"""Gate 1 (P5/WP4, G5): the human approves brief + themes — headless until
P9 (B5); this function IS the gate data contract, and the CLI surface
arrives with make slice at P8 (B22(6)).

Approval is recorded in the artifact (B5): status, gate1{approved_by, at,
notes}, created (B19(8) — the brief's first wall-clock, injected via the
`at` kwarg and never read from a clock, B22(8)), win_themes.approved, and
— T7 — the frozen copy brief.frozen.json, written through the existing
write_artifact name= seam so it is byte-equal to brief.json by
construction. Rejection declines the brief and freezes nothing. The
decision→status mapping is pinned here (B22(12), the B7-class vocabulary
split). Write order is brief → freeze → log → checkpoint so a mid-gate
crash resumes convergently (B22(10)); a crash between the gate line and
the checkpoint may leave one duplicate gate line on resume — the log is
append-only and honest about reruns.

Edits address candidates by their stable candidate_id (B22(11), landed
at P9/E2 — a web screen re-renders the list, so index addressing died
with the headless-only era). Kill and edit run first, adds are appended
last with the next id in sequence — deterministic. A human instruction
that fails raises — it is never dropped-and-reported.
"""

import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from engine.contracts import ContractError

FROZEN_BRIEF = "brief.frozen.json"

DECISIONS = ("approved", "approved_with_edits", "rejected", "auto_approved")
# B22(12): run-log gate.decision → brief.status, pinned
DECISION_TO_STATUS = {
    "approved": "approved",
    "approved_with_edits": "approved",
    "auto_approved": "approved",
    "rejected": "declined",
}


@dataclass
class GateResult:
    decision: str
    brief_path: Path
    frozen_path: Path | None
    brief_sha256: str
    converged: bool = False


def _summary(edits: dict | None) -> str | None:
    if not edits:
        return None
    return (f"kill:{len(edits.get('kill', []))} "
            f"add:{len(edits.get('add', []))} "
            f"edit:{len(edits.get('edit', []))}")


def _by_id(candidates: list[dict], cid, op: str) -> dict:
    for candidate in candidates:
        if candidate.get("candidate_id") == cid:
            return candidate
    raise ContractError(f"gate_1 {op}: unknown candidate_id {cid!r}")


def _next_candidate_id(candidates: list[dict]) -> str:
    highest = 0
    for candidate in candidates:
        cid = candidate.get("candidate_id", "")
        if cid.startswith("cand_"):
            try:
                highest = max(highest, int(cid[5:]))
            except ValueError:
                pass
    return f"cand_{highest + 1:02d}"


def _apply_edits(candidates: list[dict], edits: dict, actor: str) -> None:
    unknown = set(edits) - {"kill", "add", "edit"}
    if unknown:
        raise ContractError(f"gate_1 edits: unknown operations {sorted(unknown)}")
    for cid in edits.get("kill", []):
        candidate = _by_id(candidates, cid, "edits.kill")
        if candidate["status"] == "killed":
            raise ContractError(
                f"gate_1 edits.kill: candidate {cid} is already killed")
        candidate["status"] = "killed"
        candidate["kill_reason"] = f"killed at Gate 1 by {actor}"
    for entry in edits.get("edit", []):
        if not isinstance(entry, dict) or "candidate_id" not in entry:
            raise ContractError(
                "gate_1 edits.edit: each entry needs a candidate_id")
        extra = set(entry) - {"candidate_id", "theme", "rationale"}
        if extra:
            raise ContractError(f"gate_1 edits.edit: unknown keys {sorted(extra)}")
        candidate = _by_id(candidates, entry["candidate_id"], "edits.edit")
        for key in ("theme", "rationale"):
            if entry.get(key):
                candidate[key] = entry[key]
    for entry in edits.get("add", []):
        if not isinstance(entry, dict) or not entry.get("theme"):
            raise ContractError("gate_1 edits.add: each entry needs a theme")
        extra = set(entry) - {"theme", "rationale", "cites"}
        if extra:
            raise ContractError(f"gate_1 edits.add: unknown keys {sorted(extra)}")
        candidate = {"candidate_id": _next_candidate_id(candidates),
                     "theme": entry["theme"], "status": "proposed"}
        if entry.get("rationale"):
            candidate["rationale"] = entry["rationale"]
        if entry.get("cites"):
            candidate["cites"] = entry["cites"]  # human-authored: cites optional
        candidates.append(candidate)


def approve_gate1(pursuit, log, *, decision: str, actor: str, at: str,
                  notes: str | None = None, edits: dict | None = None,
                  wait_ms: int = 0, auto_approved: bool = False) -> GateResult:
    # ---- validation before any write
    if decision not in DECISIONS:
        raise ContractError(
            f"gate_1 decision must be one of {DECISIONS}, got {decision!r}")
    if (decision == "auto_approved") != auto_approved:
        raise ContractError(
            "auto_approved is reserved for replay: the flag and decision "
            "'auto_approved' must agree (B22(13))")
    if not actor:
        raise ContractError("gate_1 requires an actor")
    try:
        datetime.fromisoformat(at.replace("Z", "+00:00"))
    except (ValueError, AttributeError, TypeError) as exc:
        # jsonschema format checking is off — this is the date-time gate
        raise ValueError(f"gate_1 'at' must be ISO 8601: {at!r}") from exc
    if decision == "approved_with_edits" and not edits:
        raise ContractError("approved_with_edits requires edits")
    try:
        brief = pursuit.read_artifact("brief.json")
    except FileNotFoundError:
        raise ContractError("gate_1: no brief.json — nothing to approve") from None
    if "candidates" not in brief.get("win_themes", {}):
        raise ContractError(
            "gate_1: brief carries no win_themes.candidates — run win_themes first")

    status = DECISION_TO_STATUS[decision]

    # ---- idempotency / conflict (B22(10))
    if "gate_1" in pursuit.completed_stages():
        prior = pursuit.checkpoint_payload("gate_1")
        if (prior.get("decision"), prior.get("actor"), prior.get("at")) == \
                (decision, actor, at):
            frozen = pursuit.root / FROZEN_BRIEF
            return GateResult(decision=decision,
                              brief_path=pursuit.root / "brief.json",
                              frozen_path=frozen if frozen.exists() else None,
                              brief_sha256=prior["brief_sha256"],
                              converged=True)
        raise ContractError(f"gate_1 already decided: {prior['decision']!r} "
                            f"by {prior['actor']!r} at {prior['at']}")
    stamped_already = brief.get("status") in ("approved", "declined")
    if stamped_already:
        # mid-gate crash window: brief stamped, checkpoint missing — a
        # same-args call completes freeze/log/checkpoint convergently
        gate1 = brief.get("gate1", {})
        if not (brief["status"] == status and gate1.get("approved_by") == actor
                and gate1.get("at") == at):
            raise ContractError(
                "gate_1: the brief is already past the gate with a different "
                "decision")
    elif brief.get("status") != "gate1_pending":
        raise ContractError(f"gate_1: brief status must be gate1_pending, "
                            f"got {brief.get('status')!r}")

    log.emit("stage_start", stage="gate_1")

    if not stamped_already:
        if edits:
            _apply_edits(brief["win_themes"]["candidates"], edits, actor)
        if status == "approved":
            for candidate in brief["win_themes"]["candidates"]:
                if candidate["status"] == "proposed":
                    candidate["status"] = "approved"
            brief["win_themes"]["approved"] = [
                candidate["theme"]
                for candidate in brief["win_themes"]["candidates"]
                if candidate["status"] == "approved"]
        gate1 = {"approved_by": actor, "at": at}
        if notes:
            gate1["notes"] = notes
        brief["gate1"] = gate1
        brief["created"] = at  # B19(8): Gate 1 stamps the brief's datetime
        brief["status"] = status

    path = pursuit.write_artifact("bid_brief", brief)
    brief_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    log.emit("artifact", stage="gate_1", artifact={
        "kind": "bid_brief", "path": str(path), "sha256": brief_sha,
    })
    frozen_path = None
    frozen_sha = None
    if status == "approved":
        # T7: the frozen copy P7 drafters read — same dict, same serializer,
        # byte-equal to brief.json; no freeze on rejection
        frozen_path = pursuit.write_artifact("bid_brief", brief,
                                             name=FROZEN_BRIEF)
        frozen_sha = hashlib.sha256(frozen_path.read_bytes()).hexdigest()
        log.emit("artifact", stage="gate_1", artifact={
            "kind": "bid_brief", "path": str(frozen_path), "sha256": frozen_sha,
        })
    gate = {"which": "gate_1_strategy", "decision": decision, "actor": actor,
            "auto_approved": auto_approved, "wait_ms": wait_ms}
    summary = _summary(edits)
    if summary:
        gate["edits_summary"] = summary
    log.emit("gate", stage="gate_1", gate=gate)
    pursuit.checkpoint("gate_1", {
        "decision": decision, "actor": actor, "at": at,
        "brief_sha256": brief_sha, "frozen_sha256": frozen_sha,
    })
    log.emit("stage_end", stage="gate_1")
    return GateResult(decision=decision, brief_path=path,
                      frozen_path=frozen_path, brief_sha256=brief_sha)
