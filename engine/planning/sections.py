"""Slot -> section aggregation, the zero-silent-misses invariant, and
gating cascade.

Aggregation rule (pinned, B28): each sheet is a section; within a
sheet, header slots open sub-sections when present. Section title =
sheet name .strip() (EC-1: display honesty — the byte-exact name stays
on the slots' source_locator). section_id = unique-suffixed slug.

ZERO SILENT MISSES (the v1 ledger's named harvest, planner.py:483):
every slot appears in exactly one section; after mapping, every
answerable slot is exactly one of grounded / shape-skipped /
gated-skipped / explicitly-gapped — anything else raises
PlanInvariantError. A slot the plan would have silently missed is a
planner bug, never a warning.
"""

import re

from engine.contracts.slots import is_organizational


class PlanInvariantError(RuntimeError):
    """A slot the plan would have silently missed — a planner bug."""


# Shapes the mapper does not search and does not gap: the buyer wants a
# value/grid/record, not narrative — shape-skipped per B28(4), and the
# P7 drafter never requests them (its wire has no non-prose arm, B31);
# pricing grids land here and P9 owns the pricing refusal.
SKIP_SHAPES = frozenset(
    {"boolean", "numeric", "record", "table", "template_fill", "none"}
)

_SLUG = re.compile(r"[^a-z0-9]+")


def slug(text: str) -> str:
    return _SLUG.sub("-", text.lower()).strip("-")[:30] or "section"


def unique_slugs(titles: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for title in titles:
        s = slug(title)
        if s in seen:
            seen[s] += 1
            s = f"{s}-{seen[s]}"
        else:
            seen[s] = 1
        out.append(s)
    return out


def is_answerable(slot: dict) -> bool:
    """The mapper's lane: authored prose. Everything else is listed on
    its section but shape-skipped."""
    if is_organizational(slot):
        return False
    if slot.get("fill_type") == "template_fill":
        return False
    return slot.get("response_shape", "prose") not in SKIP_SHAPES


def aggregate(slots: list[dict]) -> list[dict]:
    """Section skeletons: [{section_id, title, source, slot_ids}] in
    slot order.

    Two lanes by locator shape (P16): SHEET-bearing slots (xlsx) keep
    the pre-P16 grouping byte-for-byte — header slots open
    sub-sections; sheets without headers are one section each.
    SHEETLESS slots (docx) group by HEADING: a header slot or a
    parentless slot opens a section titled by its path (an
    instruction-bearing outline section is answerable AND owns its
    section); a slot joins the section its parent opened."""
    groups: list[tuple[str, list[dict]]] = []  # (title, slots)
    current_key: tuple[str, str | None] | None = None
    for slot in slots:
        sheet = (slot.get("source_locator", {}).get("sheet") or "").strip()
        if not sheet:  # the docx lane
            opener = slot.get("is_header") or not slot.get("parent")
            if (not opener and current_key is not None
                    and current_key[0] == ""
                    and slot.get("parent") == current_key[1]):
                groups[-1][1].append(slot)
                continue
            title = (slot.get("path") or slot.get("question_text")
                     or slot["slot_id"]).strip()
            groups.append((title, [slot]))
            current_key = ("", slot["slot_id"])
            continue
        if slot.get("is_header"):
            title = f"{sheet} > {(slot.get('question_text') or slot.get('ref_id') or '').strip()}"
            groups.append((title.rstrip(" >"), [slot]))
            current_key = (sheet, slot["slot_id"])
            continue
        parent = slot.get("parent")
        if current_key is not None and current_key[0] == sheet and parent == current_key[1]:
            groups[-1][1].append(slot)
            continue
        if groups and current_key is not None and current_key[0] == sheet and current_key[1] is None:
            groups[-1][1].append(slot)
            continue
        groups.append((sheet, [slot]))
        current_key = (sheet, None)

    ids = unique_slugs([title for title, _ in groups])
    sections = []
    for section_id, (title, group) in zip(ids, groups):
        sections.append({
            "section_id": section_id,
            "title": title,
            "source": "client_structure",
            "slot_ids": [s["slot_id"] for s in group],
        })
    return sections


def cascade_gating(slots: list[dict], gapped_ids: set[str]) -> set[str]:
    """Transitive gating skip: children (and grandchildren) of a GAPPED
    gater are gated-skipped — the engine cannot know the gate's answer,
    so drafting into them would be invention. Returns skipped slot_ids.
    Dangling gate refs are tolerated (v1 rule)."""
    gates_by_id = {
        s["slot_id"]: s.get("gating", {}).get("gates", []) for s in slots
    }
    skipped: set[str] = set()
    frontier = [sid for sid in gapped_ids if gates_by_id.get(sid)]
    while frontier:
        gater = frontier.pop()
        for child in gates_by_id.get(gater, []):
            if child not in skipped:
                skipped.add(child)
                frontier.append(child)
    return skipped


def assert_zero_silent_misses(
    slots: list[dict],
    sections: list[dict],
    dispositions: dict[str, str],
) -> None:
    """Every slot sectioned exactly once; every answerable slot exactly
    one of grounded / gapped; skips must be explicit."""
    sectioned: list[str] = []
    for section in sections:
        sectioned.extend(section["slot_ids"])
    slot_ids = [s["slot_id"] for s in slots]
    if sorted(sectioned) != sorted(slot_ids):
        missing = set(slot_ids) - set(sectioned)
        extras = set(sectioned) - set(slot_ids)
        raise PlanInvariantError(
            f"slots not sectioned exactly once: missing={sorted(missing)} "
            f"extra={sorted(extras)}"
        )
    silent = [
        s["slot_id"] for s in slots
        if dispositions.get(s["slot_id"]) not in
        ("grounded", "gapped", "shape_skipped", "gated_skipped")
    ]
    if silent:
        raise PlanInvariantError(
            f"answerable slots neither grounded, skipped, nor explicitly "
            f"gapped: {silent}"
        )
