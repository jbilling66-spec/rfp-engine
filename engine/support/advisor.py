"""The chat advisor (B37/D21) — in-app orientation and how-to, NOT the
evidence pipeline (it never drafts, revises, or suggests deliverable
prose, and it cannot change anything).

Grounding is three-layer (v1 keeper design, reimplemented):
1. The corpus IS the system prompt: a deterministic concat of the
   committed docs/advisor/*.md, whose filenames double as the CLOSED
   citation vocabulary. A missing doc becomes a literal `(unavailable)`
   marker — the advisor then honestly cannot cite it.
2. The reply is a discriminated union: an ANSWER must cite ≥1 source
   from the closed vocabulary; a DECLINE names the topic and carries NO
   answer field — declining is the correct behavior and every decline
   feeds the support-gaps worklist so the documentation improves.
3. The pursuit digest is FACTS ONLY (bracket-labeled lines, no
   deliverable prose) — nothing to paraphrase.

Cache discipline: nothing per-request touches the system string; the
digest, history (capped IN CODE: last 3 turns, 500 chars per side —
never trusted from the client), and question ride the user prompt.
FakeCaller default like everything else: conversational quality is
claimed at live milestones/UAT, never before (B36(2))."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORPUS_DIR = ROOT / "docs" / "advisor"
_PROMPT = ROOT / "prompts" / "advisor" / "prompt.md"

DOC_SOURCES = ("getting-started.md", "pursuit-workflow.md",
               "gates-and-decisions.md", "review-and-revision.md",
               "share-links.md", "exports-and-writeback.md")
DIGEST_FACETS = ("pursuit-status", "gates", "sections", "packaging",
                 "gaps", "cost")
CITATION_VOCAB = frozenset(DOC_SOURCES) | frozenset(DIGEST_FACETS)

_HISTORY_TURNS = 3
_HISTORY_CHARS = 500


class AdvisorError(ValueError):
    pass


def compose_corpus() -> str:
    blocks = []
    for name in DOC_SOURCES:
        path = CORPUS_DIR / name
        body = path.read_text(encoding="utf-8") if path.exists() else \
            "(unavailable — this document is missing from the install)"
        blocks.append(f"=== SOURCE: {name} ===\n{body}")
    return "\n\n".join(blocks)


def system_prompt() -> str:
    # corpus first, stable contract last — nothing per-request in here
    return compose_corpus() + "\n\n---\n\n" + _PROMPT.read_text(
        encoding="utf-8")


def pursuit_digest(workspace: Path, pursuit_id: str) -> str:
    """Facts only. Existence check FIRST — asking about a pursuit must
    never create one (the PursuitDir mkdir trap)."""
    root = Path(workspace) / pursuit_id
    if not (root / "brief.json").exists() and not (root / "plan.json"
                                                   ).exists():
        raise FileNotFoundError(f"no pursuit {pursuit_id!r}")
    lines = []

    def _read(name):
        path = root / name
        return json.loads(path.read_text(encoding="utf-8")) \
            if path.exists() else None

    brief = _read("brief.json")
    plan = _read("plan.json")
    annotated = _read("drafts/annotated-draft.json")
    lines.append(f"[pursuit-status] {pursuit_id}: "
                 f"brief={brief.get('status') if brief else 'absent'}, "
                 f"plan={plan.get('status') if plan else 'absent'}")
    if brief and brief.get("gate1"):
        lines.append(f"[gates] gate 1: decided by "
                     f"{brief['gate1'].get('approved_by')}")
    if plan and plan.get("gate2"):
        lines.append(f"[gates] gate 2: decided by "
                     f"{plan['gate2'].get('approved_by')}")
    if plan:
        gaps = [g for s in plan.get("sections", [])
                for g in s.get("gaps", [])]
        open_gaps = sum(1 for g in gaps
                        if g.get("status") in ("open", "pinged"))
        lines.append(f"[sections] {len(plan.get('sections', []))} planned"
                     + (f"; [gaps] {open_gaps} open of {len(gaps)}"
                        if gaps else ""))
    if annotated:
        packaging = annotated.get("packaging", {})
        lines.append(f"[packaging] "
                     f"{'BLOCKED' if packaging.get('blocked') else 'clear'}"
                     f" ({packaging.get('tier1_blocks', 0)} tier-1, "
                     f"{packaging.get('waived', 0)} waived), revision "
                     f"{annotated.get('revision_n')}")
    return "\n".join(lines)


def build_user_prompt(question: str, *, digest: str = "",
                      history: list[dict] | None = None) -> str:
    parts = []
    for turn in (history or [])[-_HISTORY_TURNS:]:
        q = str(turn.get("q", ""))[:_HISTORY_CHARS]
        a = str(turn.get("a", ""))[:_HISTORY_CHARS]
        parts.append(f"[EARLIER] Q: {q}\nA: {a}")
    if digest:
        parts.append(f"[PURSUIT DIGEST]\n{digest}")
    parts.append(f"QUESTION: {question}")
    return "\n\n".join(parts)


def parse_reply(text: str) -> dict:
    """The discriminated union, whitelist-gated. A decline must not
    smuggle an answer; an answer must cite from the closed vocabulary."""
    try:
        start, end = text.index("{"), text.rindex("}") + 1
        obj = json.loads(text[start:end])
    except (ValueError, TypeError):
        raise AdvisorError("advisor wire is not a JSON object")
    if not isinstance(obj, dict):
        raise AdvisorError("advisor wire is a scalar, not an object")
    kind = obj.get("kind")
    if kind == "answer":
        answer = obj.get("answer")
        citations = [c for c in (obj.get("citations") or [])
                     if c in CITATION_VOCAB]
        if not isinstance(answer, str) or not answer.strip():
            raise AdvisorError("an answer needs text")
        if not citations:
            raise AdvisorError("an answer must cite at least one source "
                               "from the closed vocabulary")
        return {"kind": "answer", "answer": answer,
                "citations": citations}
    if kind == "not_covered":
        topic = obj.get("topic")
        if not isinstance(topic, str) or not topic.strip():
            raise AdvisorError("a decline names its topic")
        closest = [c for c in (obj.get("closest_sources") or [])
                   if c in CITATION_VOCAB]
        return {"kind": "not_covered", "topic": topic.strip(),
                "closest_sources": closest}
    raise AdvisorError(f"advisor wire kind must be answer|not_covered, "
                       f"got {kind!r}")
