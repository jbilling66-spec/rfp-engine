"""Gate 0 (P15/B70): the human confirms the engine's READING of the
package before research spends — mirroring Gate 1's skeleton
(engine/strategy/gate.py) with the intake deltas:

- The gate is CHECKPOINT-keyed, not status-keyed: win_themes owns
  `gate1_pending` and Gate 1's crash-window logic keys on the status
  vocabulary, so gate_0 adds no status value. The driver stops while
  "gate_0" is absent from completed_stages(); approval stamps a
  top-level `gate0` block (mirror of `gate1`) and writes the checkpoint.
- Three edit families, all raise-never-drop (B22(11) discipline):
  `corrections` address intake.assumptions by field path — a correction
  rewrites the brief field AND stamps the register entry `corrected`; a
  source="code" entry refuses (the number was parsed from model text —
  correct the text, and the parse follows). `answers` and `skips`
  address intake.gaps by gap_id; questioner gaps are ADVISORY and may
  all be left open — no gate consumes them (E5/A4).
- Approval blanket-confirms the register (human decisions only —
  auto_approved leaves it unconfirmed, because a register stamped
  confirmed under replay would claim a human read it).
- Rejection = REDO DOOR (Gate 2's precedent, not Gate 1's terminal
  decline): notes required, the `intake` and `bid_brief` checkpoints
  are cleared so the next advance re-runs intake against the fixed
  inbox, and neither stamp nor gate_0 checkpoint is written.
- No freeze at gate_0 — the T7 freeze stays Gate 1's.

Write order on approval: brief -> log -> checkpoint (B22(10)); a crash
between the gate line and the checkpoint may leave one duplicate gate
line on resume — the log is append-only and honest about reruns.
"""

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime

from engine.contracts.gate_key import request_digest, same_request
from engine.contracts import ContractError
from engine.intake.brief import parse_weight

DECISIONS = ("approved", "approved_with_edits", "rejected", "auto_approved")

_INDEXED = re.compile(r"^([a-z_]+)\[(\d+)\]$")


@dataclass
class Gate0Result:
    decision: str
    brief_path: object = None
    brief_sha256: str | None = None
    converged: bool = False
    proposals: list = field(default_factory=list)


def _resolve_parent(brief: dict, field: str):
    """Walk a register field path ('buyer.name',
    'requirements_matrix[3].weight_text') to (parent, leaf_key).
    Raise-never-drop: a path that does not resolve is a defect in the
    instruction, not something to skip."""
    node = brief
    parts = field.split(".")
    for part in parts[:-1]:
        m = _INDEXED.match(part)
        if m:
            key, idx = m.group(1), int(m.group(2))
            try:
                node = node[key][idx]
            except (KeyError, IndexError, TypeError):
                raise ContractError(
                    f"gate_0 correction: path {field!r} does not resolve "
                    f"at {part!r}") from None
        else:
            if not isinstance(node, dict) or part not in node:
                raise ContractError(
                    f"gate_0 correction: path {field!r} does not resolve "
                    f"at {part!r}")
            node = node[part]
    leaf = parts[-1]
    if _INDEXED.match(leaf):
        raise ContractError(
            f"gate_0 correction: {field!r} addresses a whole row — "
            f"corrections address scalar fields")
    return node, leaf


def _apply_corrections(brief: dict, corrections: list, actor: str) -> int:
    register = {e["field"]: e for e in
                brief.get("intake", {}).get("assumptions", [])}
    applied = 0
    for item in corrections:
        field = item.get("field")
        if field not in register:
            raise ContractError(
                f"gate_0 correction: {field!r} is not on the assumption "
                f"register")
        entry = register[field]
        if entry["source"] == "code":
            raise ContractError(
                f"gate_0 correction: {field!r} is code-parsed — correct "
                f"its model source text and the parse follows")
        if "value" not in item:
            raise ContractError(
                f"gate_0 correction for {field!r} needs a value")
        parent, leaf = _resolve_parent(brief, field)
        parent[leaf] = item["value"]
        entry["status"] = "corrected"
        entry["corrected_to"] = item["value"]
        entry["corrected_by"] = actor
        applied += 1
        if leaf == "weight_text":
            # keep the code-derived number consistent with its corrected
            # source: reparse, and REMOVE a number its text no longer
            # states — a stale 30.0 under corrected prose is a lie
            weight, basis = parse_weight(item["value"])
            code_field = field.replace(".weight_text", ".weight")
            if weight is None:
                parent.pop("weight", None)
                parent.pop("weight_basis", None)
                brief["intake"]["assumptions"] = [
                    e for e in brief["intake"]["assumptions"]
                    if e["field"] != code_field]
            else:
                parent["weight"] = weight
                parent["weight_basis"] = basis
                if code_field in register:
                    register[code_field]["value"] = weight
    return applied


def _apply_gap_actions(brief: dict, log, *, answers: list, skips: list,
                       actor: str, at: str, kb_root=None,
                       pursuit_id: str = "") -> tuple[int, int, list, list]:
    gaps = {g["gap_id"]: g for g in
            brief.get("intake", {}).get("gaps", [])}

    def _open_gap(gap_id):
        if gap_id not in gaps:
            raise ContractError(f"gate_0: unknown intake gap {gap_id!r}")
        gap = gaps[gap_id]
        if gap["status"] != "open":
            raise ContractError(
                f"gate_0: gap {gap_id} is {gap['status']!r} — only an "
                f"open gap takes an action")
        return gap

    proposals: list = []
    gap_lines: list[dict] = []  # emitted by the caller AFTER the brief write
    for item in answers:
        gap = _open_gap(item.get("gap_id"))
        if not str(item.get("answer", "")).strip():
            raise ContractError(
                f"gate_0: an answer for {gap['gap_id']} needs text")
        gap["status"] = "answered"
        gap["answer"] = item["answer"]
        gap["answered_by"] = actor
        gap["answered_at"] = at
        gap_lines.append({
            "gap_id": gap["gap_id"], "reason": gap["reason"],
            "question_to_human": gap["question_to_human"],
            "answered_at": at, "resolution": "answered"})
        if item.get("propose_card"):
            # P15/C10: opt-in only — the answer may ALSO teach the
            # corpus, through the steward door, never straight in
            if kb_root is None:
                raise ContractError(
                    "gate_0: propose_card requested but no kb_root is "
                    "wired — the instruction is honored or refused, "
                    "never dropped")
            from engine.kb.curation import propose_gap_answer_card
            proposals.append(propose_gap_answer_card(
                kb_root, gap=gap, pursuit_id=pursuit_id,
                operator=actor, at=at))
    for gap_id in skips:
        gap = _open_gap(gap_id)
        gap["status"] = "skipped"
        gap_lines.append({
            "gap_id": gap["gap_id"], "reason": gap["reason"],
            "question_to_human": gap["question_to_human"],
            "resolution": "descoped"})
    return len(answers), len(skips), proposals, gap_lines


def _resolve_org(pursuit, brief, org: dict, actor: str, at: str) -> str:
    """P17/C6 (B75§2): the human link step — a pursuit is bound to an
    organization by a PERSON at gate_0, never by string match (the
    document-role precedent: declared, not inferred). Link an existing
    org ({'org_id': ...}, recording the buyer's current display name as
    an alias) or mint-and-link ({'create': {'name': ...}})."""
    from engine.workspace import orgs

    workspace = pursuit.root.parent
    buyer_name = brief.get("buyer", {}).get("name", "")
    if ("org_id" in org) == ("create" in org):
        raise ContractError(
            "gate_0 org link takes exactly one of org_id (link existing) "
            "or create.name (mint and link)")
    if "org_id" in org:
        record = orgs.link_alias(workspace, org["org_id"], buyer_name)
    else:
        record = orgs.create_org(workspace, org["create"].get("name", ""),
                                 created_by=actor, at=at)
        if buyer_name:
            orgs.link_alias(workspace, record["org_id"], buyer_name)
    return record["org_id"]


def approve_gate0(pursuit, log, *, decision: str, actor: str, at: str,
                  notes: str | None = None, corrections: list | None = None,
                  answers: list | None = None, skips: list | None = None,
                  wait_ms: int = 0, auto_approved: bool = False,
                  kb_root=None, org: dict | None = None) -> Gate0Result:
    # ---- validation before any write
    if decision not in DECISIONS:
        raise ContractError(
            f"gate_0 decision must be one of {DECISIONS}, got {decision!r}")
    if (decision == "auto_approved") != auto_approved:
        raise ContractError(
            "auto_approved is reserved for replay: the flag and decision "
            "'auto_approved' must agree (B22(13))")
    if not actor:
        raise ContractError("gate_0 requires an actor")
    try:
        datetime.fromisoformat(at.replace("Z", "+00:00"))
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError(f"gate_0 'at' must be ISO 8601: {at!r}") from exc
    corrections = corrections or []
    answers = answers or []
    skips = skips or []
    if decision == "approved_with_edits" and not (corrections or answers
                                                  or skips):
        raise ContractError(
            "approved_with_edits requires corrections, answers, or skips")
    if decision == "rejected" and not (notes or "").strip():
        raise ContractError(
            "gate_0 rejection is a redo instruction — notes are required")
    try:
        brief = pursuit.read_artifact("brief.json")
    except FileNotFoundError:
        raise ContractError(
            "gate_0: no brief.json — nothing to review") from None

    # ---- idempotency / conflict (B22(10); P25 item 1: keyed on WHAT was
    # decided — (decision, actor, request digest) — never on the clock)
    digest = request_digest(decision=decision, notes=notes,
                            corrections=corrections, answers=answers,
                            skips=skips, org=org)
    if "gate_0" in pursuit.completed_stages():
        prior = pursuit.checkpoint_payload("gate_0")
        if same_request(prior, decision=decision, actor=actor, digest=digest,
                        actor_key="actor"):
            return Gate0Result(decision=decision,
                               brief_path=pursuit.root / "brief.json",
                               brief_sha256=prior["brief_sha256"],
                               converged=True)
        raise ContractError(f"gate_0 already decided: {prior['decision']!r} "
                            f"by {prior['actor']!r} at {prior['at']}")
    stamped_already = "gate0" in brief
    if stamped_already:
        # mid-gate crash window: brief stamped, checkpoint missing — a
        # same-args call completes log/checkpoint convergently
        gate0 = brief["gate0"]
        if not same_request(gate0, actor=actor, digest=digest,
                            actor_key="approved_by"):
            raise ContractError(
                "gate_0: the brief is already past the gate with a "
                "different decision")
        at = gate0.get("at", at)  # complete with the STAMP's clock (P0-5)

    log.emit("stage_start", stage="gate_0")

    if decision == "rejected":
        # the redo door: nothing is stamped, nothing is checkpointed —
        # the cleared checkpoints make the next advance re-run intake
        # against the fixed inbox
        pursuit.clear_checkpoint("intake")
        pursuit.clear_checkpoint("bid_brief")
        gate = {"which": "gate_0_intake", "decision": decision,
                "actor": actor, "auto_approved": auto_approved,
                "wait_ms": wait_ms}
        log.emit("gate", stage="gate_0", gate=gate)
        log.emit("stage_end", stage="gate_0")
        return Gate0Result(decision=decision)

    summary_parts = []
    spawned: list = []
    gap_lines: list = []
    if not stamped_already:
        if org is not None:
            # The org link stamps PRE-FREEZE, so buyer.org_id rides into
            # brief.frozen.json with no extra machinery (B75§3d); a
            # mislink is corrected through this same gate's redo door.
            org_id = _resolve_org(pursuit, brief, org, actor, at)
            brief["buyer"]["org_id"] = org_id
            summary_parts.append(f"org:{org_id}")
        applied = _apply_corrections(brief, corrections, actor)
        answered, skipped, spawned, gap_lines = _apply_gap_actions(
            brief, log, answers=answers, skips=skips, actor=actor, at=at,
            kb_root=kb_root, pursuit_id=pursuit.pursuit_id)
        if applied:
            summary_parts.append(f"correct:{applied}")
        if answered:
            summary_parts.append(f"answer:{answered}")
        if skipped:
            summary_parts.append(f"skip:{skipped}")
        if spawned:
            summary_parts.append(f"card:{len(spawned)}")
        if decision in ("approved", "approved_with_edits"):
            # blanket confirmation is a HUMAN act — replay leaves the
            # register unconfirmed rather than claiming a reader it
            # never had
            for entry in brief.get("intake", {}).get("assumptions", []):
                if entry["status"] == "unconfirmed":
                    entry["status"] = "confirmed"
        gate0 = {"approved_by": actor, "at": at, "request_sha256": digest}
        if notes:
            gate0["notes"] = notes
        brief["gate0"] = gate0

    path = pursuit.write_artifact("bid_brief", brief)
    brief_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    log.emit("artifact", stage="gate_0", artifact={
        "kind": "bid_brief", "path": str(path), "sha256": brief_sha,
    })
    for gap in gap_lines:
        # P25 item 1 (P2-11): gap lines land AFTER the brief write, so a
        # crash before the write replays none of them (the KB proposals
        # are content-keyed and replay to the same id)
        log.emit("gap", stage="gate_0", gap=gap)
    gate = {"which": "gate_0_intake", "decision": decision, "actor": actor,
            "auto_approved": auto_approved, "wait_ms": wait_ms}
    if summary_parts:
        gate["edits_summary"] = " ".join(summary_parts)
    log.emit("gate", stage="gate_0", gate=gate)
    pursuit.checkpoint("gate_0", {
        "decision": decision, "actor": actor, "at": at,
        "brief_sha256": brief_sha, "request_sha256": digest,
    })
    log.emit("stage_end", stage="gate_0")
    return Gate0Result(decision=decision, brief_path=path,
                       brief_sha256=brief_sha, proposals=spawned,
                       converged=stamped_already)
