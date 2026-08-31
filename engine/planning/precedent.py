"""The precedent lane (the owner's build-now decision, 2026-08-02; B28).

Advisory cross-pursuit hints DERIVED from approved sibling plans — no
dedicated store, pure code, never auto-applied (B24 posture: hints
inform, humans and P7 drafters decide; a hint alters no mapping
verdict, no gap, no coverage number — invariant-tested).

Matching is deterministic and EXACT-ONLY pre-production: normalized question
text (Path A slots) or normalized section title (Path B). Fuzzy
matching is explicitly out — exact-only bounds the false-hint rate to
genuine normalize collisions.

Scope note (TODO(spec-gap), A5): this scans sibling pursuit directories
under one workspace root via plain file reads (not KB retrieval — no
run-log lines). Cross-workspace/production precedent with access
logging arrives with the database.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

_NORM = re.compile(r"[^a-z0-9 ]+")


def normalize(text: str) -> str:
    return " ".join(_NORM.sub(" ", text.lower()).split())


@dataclass
class PriorPlan:
    pursuit_id: str
    # normalized question/title -> (section_id, kb_ids)
    question_index: dict[str, tuple[str, list[str]]] = field(default_factory=dict)
    title_index: dict[str, tuple[str, list[str]]] = field(default_factory=dict)


def scan_prior_plans(pursuits_root: Path, *, self_id: str
                     ) -> tuple[list[PriorPlan], list[str]]:
    """-> (priors sorted by pursuit_id, skipped-diagnostics). Only
    APPROVED sibling plans count; unreadable siblings are skipped and
    named, never crashed on."""
    priors: list[PriorPlan] = []
    skipped: list[str] = []
    root = Path(pursuits_root)
    if not root.is_dir():
        return priors, skipped
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or entry.name == self_id:
            continue
        plan_path = entry / "plan.json"
        if not plan_path.is_file():
            continue
        try:
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            skipped.append(f"{entry.name}: unreadable plan.json")
            continue
        if plan.get("status") != "approved":
            continue
        prior = PriorPlan(pursuit_id=entry.name)
        kb_ids_by_section = {
            s["section_id"]: [h["kb_id"] for h in s.get("kb_hits", [])]
            for s in plan.get("sections", [])
        }
        for section in plan.get("sections", []):
            sid = section["section_id"]
            prior.title_index.setdefault(
                normalize(section.get("title", "")),
                (sid, kb_ids_by_section.get(sid, [])),
            )
        slots_ref = plan.get("slots_ref")
        if slots_ref:
            try:
                container = json.loads(
                    (entry / slots_ref).read_text(encoding="utf-8")
                )
                questions_by_slot = {
                    s["slot_id"]: s.get("question_text", "")
                    for s in container.get("slots", [])
                }
            except (OSError, json.JSONDecodeError):
                skipped.append(f"{entry.name}: unreadable {slots_ref}")
                questions_by_slot = {}
            for section in plan.get("sections", []):
                sid = section["section_id"]
                for slot_id in section.get("slot_ids", []):
                    question = questions_by_slot.get(slot_id)
                    if question:
                        prior.question_index.setdefault(
                            normalize(question),
                            (sid, kb_ids_by_section.get(sid, [])),
                        )
        priors.append(prior)
    return priors, skipped


def attach_precedents(sections: list[dict], priors: list[PriorPlan], *,
                      texts_by_section: dict[str, list[str]]) -> None:
    """Mutates sections in place: adds precedents[] where an exact match
    exists. Path-A sections match on any of their slots' question texts;
    every section also matches on its own title. Omitted entirely when
    nothing matches (writers-omit)."""
    for section in sections:
        found: list[dict] = []
        questions = [
            normalize(t) for t in texts_by_section.get(section["section_id"], [])
        ]
        title_norm = normalize(section["title"])
        for prior in priors:
            hit = None
            note = None
            for q in questions:
                if q in prior.question_index:
                    hit = prior.question_index[q]
                    note = "exact question match"
                    break
            if hit is None and title_norm and title_norm in prior.title_index:
                hit = prior.title_index[title_norm]
                note = "exact title match"
            if hit is not None:
                prior_section, kb_ids = hit
                item = {
                    "pursuit_id": prior.pursuit_id,
                    "section_id": prior_section,
                    "note": note,
                }
                if kb_ids:
                    item["kb_ids"] = kb_ids
                found.append(item)
        if found:
            section["precedents"] = sorted(found, key=lambda p: p["pursuit_id"])
