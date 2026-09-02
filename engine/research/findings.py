"""Research stage pair (P4/WP3): bid brief + KB + optional pack → findings
cited into the brief.

Model proposes, code writes (the P2/P3 shape): code derives the abstract
topics (S6 — the model invents no queries), drives every KB retrieval through
the traced card_search/targeted_open choke point, and owns the citedness
gates — an internal finding must cite a card that was actually opened, an
airgapped external finding must cite a URL the pack actually carries.
Untraceable citations are dropped and reported, never silently kept.

Stage split (B21(7), amended P25 item 1 / register P1-12): BOTH stages are
guarded by their checkpoints. `research_internal` always was; `research_external`
was an unguarded deterministic rerun whose "converges byte-identically" held
only under FakeCaller — live or via handoff it was a second external call that
replaced the findings. It now skips on its own checkpoint (written since P4,
read by nobody until P25) and the report reads back what the stage wrote. The
stage also refuses a brief that is past Gate 1 (approved/declined, or frozen):
a research rerun may never mutate a gated brief (T7), which closes the Gate-1
crash-window rewrite the driver used to permit. As the second writer of brief.json the stage REPLACES the research
fields (never appends) and sorts findings with a code-owned key, so a rerun
converges byte-identically (N2) — and, like P3, writes no wall-clock.

Both researchers always run (R1) — exactly two mid-tier agent_calls in every
mode, every FRESH run; a rerun over a checkpointed stage spends nothing. In airgapped mode with no pack uploaded, the external call
still happens with an explicit no-material line and the absence is a gap
record, never a silent skip.
"""

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from engine.contracts import ContractError
from engine.kb import UseRestrictedCard, card_search, targeted_open
from engine.llm.frames import wrap_kb_card, wrap_research
from engine.research.pack import ResearchPack, load_pack
from engine.research.topics import assert_abstracted, derive_topics, forbidden_tokens

ROOT = Path(__file__).resolve().parents[2]
_INTERNAL_PROMPT = ROOT / "prompts" / "internal_researcher" / "prompt.md"
_EXTERNAL_PROMPT = ROOT / "prompts" / "external_researcher" / "prompt.md"

SOURCE_KINDS = ["internal_kb", "research_pack", "web"]


@dataclass
class ResearchReport:
    pursuit_id: str
    status: str = "complete"  # complete | refused
    warnings: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    findings: list[dict] = field(default_factory=list)
    brief_path: Path | None = None


# --------------------------------------------------------------- wire parse


def _parse_findings(text: str, agent: str) -> tuple[list, list[str]]:
    try:
        raw = json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ContractError(f"{agent} returned unparseable JSON: {exc}") from exc
    entries = raw.get("findings") if isinstance(raw, dict) else None
    return (entries if isinstance(entries, list) else []), []


def _take_topic(entry: dict, topics: list[str], label: str, cleared: list[str]) -> str:
    topic = entry.get("topic")
    if topic not in topics:
        cleared.append(f"{label}.topic: out-of-vocab {topic!r} -> other")
        return "other"
    return topic


def parse_wire_internal(text: str, *, opened_ids: set[str],
                        topics: list[str]) -> tuple[list[dict], list[str]]:
    """Whitelist the internal researcher's proposal. The citedness gate is
    code: a kb_id that was never opened may not enter the brief."""
    entries, cleared = _parse_findings(text, "internal_researcher")
    findings: list[dict] = []
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict) or not entry.get("claim"):
            cleared.append(f"findings[{i}]: malformed entry dropped")
            continue
        kb_id = entry.get("kb_id")
        if kb_id not in opened_ids:
            cleared.append(
                f"findings[{i}].kb_id: uncited card {kb_id!r} — finding dropped")
            continue
        finding = {
            "claim": entry["claim"],
            "topic": _take_topic(entry, topics, f"findings[{i}]", cleared),
            "source_kind": "internal_kb",
            "source": kb_id,
        }
        if entry.get("detail"):
            finding["detail"] = entry["detail"]
        findings.append(finding)
    return findings, cleared


def parse_wire_external(text: str, *, allowed_urls: list[str] | None,
                        topics: list[str],
                        source_kind: str) -> tuple[list[dict], list[str]]:
    """Whitelist the external researcher's proposal. Airgapped runs pass the
    pack's URLs as allowed_urls — the model may not invent sources; smoke
    modes (full_web/allowlist) pass None and get a syntactic check only
    (real allowlist enforcement is an A6 item, B21(8))."""
    entries, cleared = _parse_findings(text, "external_researcher")
    findings: list[dict] = []
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict) or not entry.get("claim"):
            cleared.append(f"findings[{i}]: malformed entry dropped")
            continue
        url = entry.get("source_url")
        if not url or not url.startswith(("http://", "https://")):
            cleared.append(f"findings[{i}].source_url: missing or non-http — dropped")
            continue
        if allowed_urls is not None and url not in allowed_urls:
            cleared.append(
                f"findings[{i}].source_url: {url!r} not in the pack — finding dropped")
            continue
        finding = {
            "claim": entry["claim"],
            "topic": _take_topic(entry, topics, f"findings[{i}]", cleared),
            "source_kind": source_kind,
            "source": url,
        }
        if entry.get("detail"):
            finding["detail"] = entry["detail"]
        findings.append(finding)
    return findings, cleared


# ------------------------------------------------------------------ stage


def _sorted_findings(findings: list[dict]) -> list[dict]:
    # code-owned ordering: the brief must not depend on model output order
    return sorted(findings, key=lambda f: (
        f["source_kind"], f["topic"], f["source"], f["claim"]))


def run_research(pursuit, caller, log, store, *, mode: str,
                 pack: Path | None = None) -> ResearchReport:
    report = ResearchReport(pursuit_id=pursuit.pursuit_id)

    # Refusal gate BEFORE any spend: research needs a brief to research for.
    try:
        brief = pursuit.read_artifact("brief.json")
    except FileNotFoundError:
        log.emit("error", stage="research_internal", error={
            "code": "missing_brief",
            "message": "no brief.json in the pursuit workspace — run intake first",
            "recoverable": True,
            "action_taken": "surfaced_to_human",
        })
        report.status = "refused"
        return report
    if brief.get("status") in ("approved", "declined") or (
            pursuit.root / "brief.frozen.json").exists():
        log.emit("error", stage="research_internal", error={
            "code": "brief_frozen",
            "message": "the brief is past Gate 1 — a research rerun may not "
                       "mutate a gated brief (T7; P25 item 1, P1-12)",
            "recoverable": False,
            "action_taken": "surfaced_to_human",
        })
        report.status = "refused"
        return report

    topics = derive_topics(brief)
    forbidden = forbidden_tokens(brief)
    for topic in topics:
        assert_abstracted(topic, forbidden)  # S6: raise before any query lands
    report.topics = topics

    if "research_internal" not in pursuit.completed_stages():
        log.emit("stage_start", stage="research_internal")
        opened: dict[str, tuple[str, str]] = {}
        warnings: list[str] = []
        for topic in topics:
            found = card_search(store, topic, log=log, stage="research_internal",
                                agent="internal_researcher")
            top = found.results[0] if found.results else None
            if top is None or top.kb_id in opened:
                continue
            try:
                body = targeted_open(store, top.kb_id, log=log,
                                     stage="research_internal",
                                     agent="internal_researcher", query=topic)
            except UseRestrictedCard:
                warnings.append(f"{top.kb_id}: use_restriction card skipped (D2)")
                continue
            opened[top.kb_id] = (top.card.get("title", ""), body)

        system = _INTERNAL_PROMPT.read_text(encoding="utf-8")
        parts = ["Abstracted research topics:\n"
                 + "\n".join(f"- {t}" for t in topics)]
        parts += [wrap_kb_card(kb_id, title, body)
                  for kb_id, (title, body) in opened.items()]
        if not opened:
            parts.append("No knowledge-base cards matched the topics.")
        result = caller.call("internal_researcher", tier="mid",
                             prompt="\n\n".join(parts), system=system,
                             stage="research_internal")
        findings, cleared = parse_wire_internal(
            result.text, opened_ids=set(opened), topics=topics)
        pursuit.checkpoint("research_internal", {
            "topics": topics,
            "findings": findings,
            "cards_opened": sorted(opened),
            "warnings": warnings + cleared,
        })
        log.emit("stage_end", stage="research_internal")

    if "research_external" in pursuit.completed_stages():
        # P25 item 1 (P1-12): the external call is checkpointed like the
        # internal one — a rerun never re-spends or rewrites the brief;
        # the report reads back what the stage wrote.
        done = pursuit.read_artifact("brief.json")
        report.findings = done["buyer"].get("research_findings", [])
        report.brief_path = pursuit.root / "brief.json"
        return report

    log.emit("stage_start", stage="research_external")
    internal = pursuit.checkpoint_payload("research_internal")
    # always merge from the checkpoint — fresh path == resume path (B21(7))
    topics = internal["topics"]
    report.warnings.extend(internal["warnings"])

    pack_obj: ResearchPack | None = None
    if mode == "airgapped":
        if pack is not None:
            pack_obj = load_pack(Path(pack))  # malformed pack fails loudly
            log.emit("artifact", stage="research_external", artifact={
                "kind": "research_pack",
                "path": str(pack_obj.path),
                "sha256": pack_obj.sha256,
            })
        else:
            log.emit("gap", stage="research_external", gap={
                "gap_id": f"gap_{pursuit.pursuit_id}_research_01",
                "reason": "needs_sme",
                "question_to_human": "[research_pack] No research pack uploaded — "
                                     "provide one or confirm external research is "
                                     "waived for this pursuit.",
                "resolution": "unresolved",
            })

    system = _EXTERNAL_PROMPT.read_text(encoding="utf-8")
    parts = [f"Research mode for this run: {mode}.",
             "Abstracted research topics:\n" + "\n".join(f"- {t}" for t in topics)]
    if pack_obj is not None:
        parts.append(wrap_research(pack_obj.path.name,
                                   pack_obj.path.read_text(encoding="utf-8").strip()))
    elif mode == "airgapped":
        parts.append("No external research material was provided for this run.")
    result = caller.call("external_researcher", tier="mid",
                         prompt="\n\n".join(parts), system=system,
                         stage="research_external")
    if mode == "airgapped":
        allowed = [s.source_url for s in pack_obj.sections] if pack_obj else []
        external, cleared = parse_wire_external(
            result.text, allowed_urls=allowed, topics=topics,
            source_kind="research_pack")
    else:
        external, cleared = parse_wire_external(
            result.text, allowed_urls=None, topics=topics, source_kind="web")
    report.warnings.extend(cleared)

    report.findings = _sorted_findings(internal["findings"] + external)
    brief = pursuit.read_artifact("brief.json")
    brief["buyer"]["research_findings"] = report.findings  # replace, never append
    brief["buyer"]["research_mode_used"] = mode
    path = pursuit.write_artifact("bid_brief", brief)
    report.brief_path = path
    brief_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    log.emit("artifact", stage="research_external", artifact={
        "kind": "bid_brief", "path": str(path), "sha256": brief_sha,
    })
    pursuit.checkpoint("research_external", {
        "brief_sha256": brief_sha,
        "pack_sha256": pack_obj.sha256 if pack_obj else None,
    })
    log.emit("stage_end", stage="research_external")
    return report
