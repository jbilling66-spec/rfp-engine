"""Win-Theme Strategist stage (P5/WP4): brief + research findings → 6–8
candidate angles, judge-killed to 2–3, written into the brief for Gate 1.

Model proposes, code writes (the P2–P4 shape): code renders the brief
digest and findings block, the frontier model is called twice under one
stage — generate (divergence) then judge (convergence), G4's two cognitive
moves (B22(1)) — and code owns the citedness gate: a candidate citing a
source the brief's research_findings do not carry is dropped and reported
(B22(3)). Counts are clamped, never raised: over-generation keeps the
first 8, excess keeps are force-killed, and under-runs are warnings the
Gate-1 human resolves (B22(2)). Killed candidates are RETAINED with their
kill_reason — the artifact, not a checkpoint, carries the record of why an
angle died (WP4, B23).

The model calls are guarded by the win_themes checkpoint; the brief write
always replays from the checkpoint payload — fresh path == resume path
(B21(7)). The stage writes no wall-clock and moves status to
gate1_pending; approval, timestamps, and the T7 freeze belong to Gate 1
(engine/strategy/gate.py). Candidate wire order is preserved, not
code-sorted — generation order is meaningful and the wire itself is
deterministic (B22(4)).
"""

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from engine.contracts import ContractError
from engine.llm.frames import wrap_brief_context, wrap_findings

ROOT = Path(__file__).resolve().parents[2]
_STRATEGIST_PROMPT = ROOT / "prompts" / "win_theme_strategist" / "prompt.md"

GENERATE_MIN, GENERATE_MAX = 6, 8
KEEP_MIN, KEEP_MAX = 2, 3


@dataclass
class StrategyReport:
    pursuit_id: str
    status: str = "complete"  # complete | refused
    warnings: list[str] = field(default_factory=list)
    candidates: list[dict] = field(default_factory=list)
    brief_path: Path | None = None


# --------------------------------------------------------------- wire parse


def _parse_wire(text: str, key: str) -> list:
    try:
        raw = json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ContractError(
            f"win_theme_strategist returned unparseable JSON: {exc}") from exc
    entries = raw.get(key) if isinstance(raw, dict) else None
    return entries if isinstance(entries, list) else []


def parse_wire_candidates(text: str, *, allowed_sources: set[str]
                          ) -> tuple[list[dict], list[str]]:
    """Whitelist the generate call's proposal. The citedness gate is code:
    a cite the brief's findings do not carry is removed and reported, and a
    candidate with no traceable cite left is dropped (B22(3))."""
    entries = _parse_wire(text, "candidates")
    cleared: list[str] = []
    candidates: list[dict] = []
    seen: set[str] = set()
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict) or not entry.get("theme"):
            cleared.append(f"candidates[{i}]: malformed entry dropped")
            continue
        theme = entry["theme"]
        if theme in seen:
            cleared.append(f"candidates[{i}]: duplicate theme dropped")
            continue
        raw_cites = entry.get("cites")
        cites: list[str] = []
        for cite in (raw_cites if isinstance(raw_cites, list) else []):
            if cite not in allowed_sources:
                cleared.append(
                    f"candidates[{i}].cites: unknown source {cite!r} removed")
            elif cite not in cites:
                cites.append(cite)
        if not cites:
            cleared.append(
                f"candidates[{i}].cites: no traceable source — candidate dropped")
            continue
        seen.add(theme)
        candidate = {"theme": theme, "cites": cites, "status": "proposed"}
        if entry.get("rationale"):
            candidate["rationale"] = entry["rationale"]
        candidates.append(candidate)
    return candidates, cleared


def parse_wire_verdicts(text: str, n: int) -> tuple[dict[int, dict], list[str]]:
    """Whitelist the judge call's verdicts: 1-based indexes into the
    rendered candidate list; out-of-range, duplicate, and unknown-verdict
    entries are dropped and reported."""
    entries = _parse_wire(text, "verdicts")
    cleared: list[str] = []
    verdicts: dict[int, dict] = {}
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            cleared.append(f"verdicts[{i}]: malformed entry dropped")
            continue
        idx = entry.get("candidate")
        if not isinstance(idx, int) or isinstance(idx, bool) or not 1 <= idx <= n:
            cleared.append(f"verdicts[{i}].candidate: out of range {idx!r} — dropped")
            continue
        if idx in verdicts:
            cleared.append(
                f"verdicts[{i}]: duplicate verdict for candidate {idx} dropped")
            continue
        verdict = entry.get("verdict")
        if verdict not in ("keep", "kill"):
            cleared.append(f"verdicts[{i}].verdict: unknown {verdict!r} — dropped")
            continue
        kept_entry = {"verdict": verdict}
        if entry.get("reason"):
            kept_entry["reason"] = entry["reason"]
        verdicts[idx] = kept_entry
    return verdicts, cleared


# ----------------------------------------------------------------- renders


def _brief_digest(brief: dict) -> str:
    # code-owned, deterministic, only present fields
    buyer = brief.get("buyer", {})
    proc = brief.get("procurement", {})
    lines = []
    if buyer.get("name"):
        vertical = f" ({buyer['vertical']})" if buyer.get("vertical") else ""
        lines.append(f"Buyer: {buyer['name']}{vertical}")
    if buyer.get("incumbent"):
        lines.append(f"Incumbent: {buyer['incumbent']}")
    if proc.get("what_is_bought"):
        lines.append(f"What is bought: {proc['what_is_bought']}")
    if buyer.get("terminology"):
        lines.append("Buyer terminology: " + ", ".join(buyer["terminology"]))
    return "\n".join(lines)


def _findings_block(findings: list[dict]) -> str:
    lines = []
    for f in findings:  # brief order — already code-sorted by P4
        line = f"- ({f['source_kind']}) {f['source']} | {f['topic']}: {f['claim']}"
        if f.get("detail"):
            line += f" — {f['detail']}"
        lines.append(line)
    return "\n".join(lines)


def _candidates_block(candidates: list[dict]) -> str:
    # rendered from the POST-PARSE list so verdict indexes cannot drift
    blocks = []
    for i, c in enumerate(candidates, start=1):
        entry = f"{i}. {c['theme']}"
        if c.get("rationale"):
            entry += f"\n   rationale: {c['rationale']}"
        entry += "\n   cites: " + ", ".join(c["cites"])
        blocks.append(entry)
    return "Candidates:\n" + "\n".join(blocks)


# ------------------------------------------------------------------ stage


def run_win_themes(pursuit, caller, log) -> StrategyReport:
    report = StrategyReport(pursuit_id=pursuit.pursuit_id)

    # Refusal gates BEFORE any spend (the research pattern).
    try:
        brief = pursuit.read_artifact("brief.json")
    except FileNotFoundError:
        log.emit("error", stage="win_themes", error={
            "code": "missing_brief",
            "message": "no brief.json in the pursuit workspace — run intake first",
            "recoverable": True,
            "action_taken": "surfaced_to_human",
        })
        report.status = "refused"
        return report
    findings = brief.get("buyer", {}).get("research_findings") or []
    if not findings:
        log.emit("error", stage="win_themes", error={
            "code": "missing_research",
            "message": "brief carries no research findings — themes must cite "
                       "buyer research (WP4); run research first",
            "recoverable": True,
            "action_taken": "surfaced_to_human",
        })
        report.status = "refused"
        return report
    if brief.get("status") in ("approved", "declined"):
        log.emit("error", stage="win_themes", error={
            "code": "brief_frozen",
            "message": "the brief is past Gate 1 — a stage rerun may not "
                       "mutate a gated brief (T7, B22(7))",
            "recoverable": False,
            "action_taken": "surfaced_to_human",
        })
        report.status = "refused"
        return report

    log.emit("stage_start", stage="win_themes")

    if "win_themes" not in pursuit.completed_stages():
        warnings: list[str] = []
        digest = _brief_digest(brief)
        allowed = {f["source"] for f in findings}
        system = _STRATEGIST_PROMPT.read_text(encoding="utf-8")

        result = caller.call(
            "win_theme_strategist", tier="frontier",
            prompt="\n\n".join(["Task: generate.",
                                wrap_brief_context(digest),
                                wrap_findings(_findings_block(findings))]),
            system=system, stage="win_themes")
        candidates, cleared = parse_wire_candidates(
            result.text, allowed_sources=allowed)
        warnings.extend(cleared)
        if len(candidates) > GENERATE_MAX:
            warnings.append(f"candidates[{GENERATE_MAX}:]: over-generation "
                            f"truncated to {GENERATE_MAX}")
            candidates = candidates[:GENERATE_MAX]
        elif len(candidates) < GENERATE_MIN:
            warnings.append(f"only {len(candidates)} candidates generated "
                            f"(target {GENERATE_MIN}-{GENERATE_MAX})")
        # Stable ids, code-assigned in generation order (B37/E2): Gate-1
        # edits address candidates by id, and killed candidates keep theirs.
        for i, candidate in enumerate(candidates, start=1):
            candidate["candidate_id"] = f"cand_{i:02d}"

        result = caller.call(
            "win_theme_strategist", tier="frontier",
            prompt="\n\n".join(["Task: judge.",
                                wrap_brief_context(digest),
                                _candidates_block(candidates)]),
            system=system, stage="win_themes")
        verdicts, cleared = parse_wire_verdicts(result.text, len(candidates))
        warnings.extend(cleared)

        kept = 0
        for i, candidate in enumerate(candidates, start=1):
            verdict = verdicts.get(i)
            if verdict is None:
                # G4's convergence bias: an unjudged candidate dies
                candidate["status"] = "killed"
                candidate["kill_reason"] = "no judge verdict — killed by default"
                warnings.append(f"candidate {i}: no judge verdict — killed")
            elif verdict["verdict"] == "kill":
                candidate["status"] = "killed"
                candidate["kill_reason"] = verdict.get(
                    "reason", "killed by judge without a stated reason")
            elif kept >= KEEP_MAX:
                candidate["status"] = "killed"
                candidate["kill_reason"] = (f"kept beyond the {KEEP_MIN}-"
                                            f"{KEEP_MAX} window — force-killed "
                                            f"by count gate")
                warnings.append(f"candidate {i}: kept beyond {KEEP_MAX} — "
                                f"force-killed")
            else:
                kept += 1  # status stays "proposed"
        if kept < KEEP_MIN:
            warnings.append(f"only {kept} candidates survive the judge (target "
                            f"{KEEP_MIN}-{KEEP_MAX}) — add at Gate 1 if needed")

        pursuit.checkpoint("win_themes", {
            "candidates": candidates,
            "warnings": warnings,
        })

    # always write from the checkpoint — fresh path == resume path (B21(7))
    payload = pursuit.checkpoint_payload("win_themes")
    report.candidates = payload["candidates"]
    report.warnings.extend(payload["warnings"])
    brief = pursuit.read_artifact("brief.json")
    brief["win_themes"] = {"candidates": payload["candidates"]}  # replace
    brief["status"] = "gate1_pending"
    path = pursuit.write_artifact("bid_brief", brief)
    report.brief_path = path
    log.emit("artifact", stage="win_themes", artifact={
        "kind": "bid_brief", "path": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    })
    log.emit("stage_end", stage="win_themes")
    return report
