"""The attribution join — the mechanism the whole flywheel rests on.

RUN_LOG_DESIGN states it plainly: feedback events and kb_retrieval lines
join on pursuit_id + section_id, and "that join is the whole point — it
is what lets you ask 'the sections reviewers rewrote hardest, which KB
cards fed them?'". Without the run log the flywheel knows a section was
bad but not what made it bad.

P7 emitted the `cite` line for every drafted section — including ones
that cited nothing — precisely so this join would key on it (B31(4)).
This module is that join, finally written.
"""

from collections import defaultdict


def cards_by_section(records: list[dict]) -> dict[tuple[str, str], set[str]]:
    """(pursuit_id, section_id) -> the kb_ids cited into that section.

    Reads `cite` steps only. cards_returned is what search found and
    cards_opened is what the drafter read; neither is evidence the
    content reached the page, and attributing an edit to a card the
    drafter merely looked at would sink cards for text they never
    wrote."""
    out: dict[tuple[str, str], set[str]] = defaultdict(set)
    for record in records:
        if record.get("record_type") != "kb_retrieval":
            continue
        kb = record["kb"]
        if kb.get("step") != "cite":
            continue
        section_id = (record.get("target") or {}).get("section_id")
        if not section_id:
            continue
        key = (record["pursuit_id"], section_id)
        out[key].update(kb.get("cards_cited") or ())
    return dict(out)


def edits_by_section(events: list[dict]) -> dict[tuple[str, str], list[dict]]:
    """(pursuit_id, section_id) -> the human edits landed on it.

    Only `edit` events carry before/after text. A comment asks the agent
    to change something and the agent's revision is the engine's own
    work; attributing that to a card would score the engine against
    itself."""
    out: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for event in events:
        if event.get("kind") != "edit":
            continue
        section_id = event.get("section_id")
        if not section_id:
            continue
        if event.get("before") is None or event.get("after") is None:
            continue
        out[(event["pursuit_id"], section_id)].append(event)
    return dict(out)


def join(records: list[dict], events: list[dict]) -> list[dict]:
    """One row per (section, edit) pair carrying the cards that fed it.

    A section edited but citing nothing yields no rows: there is no card
    to attribute the edit to, and inventing one would be worse than the
    silence. A section citing cards but never edited DOES yield a row
    with an empty edit list — that is a survival observation of 1.0 and
    dropping it would bias the metric toward whatever got rewritten."""
    cited = cards_by_section(records)
    edited = edits_by_section(events)
    rows = []
    for (pursuit_id, section_id), cards in sorted(cited.items()):
        if not cards:
            continue
        rows.append({
            "pursuit_id": pursuit_id,
            "section_id": section_id,
            "cards": sorted(cards),
            "edits": edited.get((pursuit_id, section_id), []),
        })
    return rows
