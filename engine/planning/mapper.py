"""The KB Mapper — pure code (B28 roster deviation from the spec's
Mid-tier agent, B21(4)'s 'code drives retrieval' carried to its
conclusion: there is no cognitive job left once search is code-driven
and ping text is code-composed, so there is no model call and a Path-A
plan is byte-reproducible).

Per answerable slot: one card_search on the slot's question text
(bare query — the replay contract), verdict by engine.planning
.confidence, section kb_hits = union of above-floor hits deduped by
kb_id keeping max score. EMPTY is decided HERE, never by the store
("the caller decides what empty means"): kb.empty_result on the logged
retrieval is the precondition the gap cites.

Two passes: search-and-verdict first, THEN the gating cascade, THEN gap
composition — a gated-skipped slot must not leave a gap behind.
"""

from engine.kb import card_search
from engine.planning.confidence import RETRIEVAL_FLOOR, confidence, verdict
from engine.planning.sections import cascade_gating, is_answerable

_PING_LINE_2 = (
    "The knowledge base has no grounding for this — provide content, "
    "approve omission, or choose a reframe (the engine will not draft "
    "around it)."
)


def compose_ping(section_title: str, label: str, ask: str,
                 excluded_count: int = 0) -> str:
    """The 2-line gap ping, code-composed (B24: the engine flags; the
    human disposes). When use-restricted cards were withheld from the
    search, the ping says so — a gap that can explain itself at Gate 2
    instead of shrugging."""
    line2 = _PING_LINE_2
    if excluded_count:
        line2 += (f" ({excluded_count} use-restricted card(s) were excluded "
                  f"from this search)")
    return f"[{section_title} / {label}] {ask}\n{line2}"


def map_sections(store, sections: list[dict], slots_by_id: dict[str, dict],
                 *, log, stage: str) -> dict[str, str]:
    """Mutates sections in place: adds kb_hits and gaps (gap items carry
    NO gap_id yet — numbering happens once, over the whole plan, in the
    stage that owns emission order). Returns slot_id -> disposition
    (grounded | gapped | shape_skipped | gated_skipped)."""
    dispositions: dict[str, str] = {}
    searched: dict[str, tuple[str, object]] = {}  # slot_id -> (verdict, result)

    # Pass 1 — search and verdict.
    for section in sections:
        for slot_id in section["slot_ids"]:
            slot = slots_by_id[slot_id]
            if not is_answerable(slot):
                dispositions[slot_id] = "shape_skipped"
                continue
            result = card_search(
                store, slot.get("question_text", ""), log=log, stage=stage,
                agent="kb_mapper",
                target={k: v for k, v in {
                    "section_id": section["section_id"],
                    "slot_ref_id": slot.get("ref_id"),
                }.items() if v is not None},
            )
            call = verdict([r.score for r in result.results])
            searched[slot_id] = (call, result)
            dispositions[slot_id] = "grounded" if call == "grounded" else "gapped"

    # Pass 2 — gating cascade: children of a gapped gater are skipped,
    # not gapped — the engine cannot know the gate's answer yet.
    gapped = {sid for sid, d in dispositions.items() if d == "gapped"}
    for slot_id in cascade_gating(list(slots_by_id.values()), gapped):
        if dispositions.get(slot_id) in ("grounded", "gapped"):
            dispositions[slot_id] = "gated_skipped"

    # Pass 3 — assemble hits and gaps from the final dispositions.
    for section in sections:
        hits: dict[str, float] = {}
        gaps: list[dict] = []
        for slot_id in section["slot_ids"]:
            if slot_id not in searched:
                continue
            call, result = searched[slot_id]
            if dispositions[slot_id] == "grounded":
                for r in result.results:
                    if r.score >= RETRIEVAL_FLOOR:
                        hits[r.kb_id] = max(hits.get(r.kb_id, 0.0), r.score)
            elif dispositions[slot_id] == "gapped":
                slot = slots_by_id[slot_id]
                gaps.append({
                    "slot_id": slot_id,  # the structural gap->slot join (E1)
                    "kind": call,  # no_content | thin_content
                    "question_to_human": compose_ping(
                        section["title"],
                        slot.get("ref_id") or slot_id,
                        slot.get("question_text", ""),
                        excluded_count=len(result.excluded),
                    ),
                    "status": "open",
                })
        if hits:
            section["kb_hits"] = [
                {"kb_id": kb_id, "confidence": confidence(score)}
                for kb_id, score in sorted(
                    hits.items(), key=lambda kv: (-kv[1], kv[0])
                )
            ]
        if gaps:
            section["gaps"] = gaps

    return dispositions
