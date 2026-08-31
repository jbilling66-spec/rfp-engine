"""The Feedback Learner's routing step: an edit becomes a lesson with an
address.

KB_DESIGN's table is the map — factual edits go to the Fact Sheet or the
corpus, tone to the voice spec, length and structure and strategy to the
playbook. This module applies it, records the decision on the event
(flywheel_routing), and opens a proposal so a human sees the diff.

Two disciplines worth naming:

* The routing decision is written back as a REVISED EVENT LINE, not an
  in-place mutation — the same append-only, last-wins shape outcomes use
  (D30). Nothing is erased, and re-running the learner over a growing
  record converges instead of drifting.
* edit_reason is INFERRED where a human did not supply one (WP8's
  specified shape: inferred and human-correctable). It is never required
  at write time, because demanding a taxonomy choice mid-review is how
  you get everything labelled "other".
"""

import re

# KB_DESIGN's routing table, as data.
ROUTE = {
    "factual": "fact_sheet",
    "tone": "voice_spec",
    "length": "playbook",
    "structure": "playbook",
    "strategy": "playbook",
    "compliance": "validation_tuning",
    "other": "none",
}

_NUMERIC = re.compile(r"\d")


def infer_edit_reason(event: dict, *, voice_terms=()) -> str:
    """WP8's inferred-and-correctable shape. A human-supplied reason
    always wins; this only fills silence.

    Deliberately conservative: it claims `factual` only when the numbers
    actually changed, and `tone` only when a prohibited term disappeared.
    Everything else is `other` rather than a confident guess, because a
    wrong route sends a lesson to the wrong home and a human then has to
    notice it there."""
    if event.get("edit_reason"):
        return event["edit_reason"]
    before = event.get("before") or ""
    after = event.get("after") or ""

    if set(_NUMERIC.findall(before)) != set(_NUMERIC.findall(after)):
        return "factual"
    lowered_before, lowered_after = before.lower(), after.lower()
    for term in voice_terms:
        if term in lowered_before and term not in lowered_after:
            return "tone"
    if len(after.split()) < len(before.split()) * 0.6:
        return "length"
    return "other"


def route_of(edit_reason: str) -> str:
    return ROUTE.get(edit_reason, "none")


def revised_event(event: dict, *, target: str, action_taken: str,
                  at: str) -> dict:
    """The append-only routing write (D30): a copy of the event carrying
    flywheel_routing, appended so the original line stays intact and the
    lane reads last-wins."""
    return {**event, "flywheel_routing": {
        "target": target, "action_taken": action_taken, "processed_at": at}}


def is_processed(event: dict) -> bool:
    return bool((event.get("flywheel_routing") or {}).get("processed_at"))


def route_edits(events: list[dict], store, *, at: str,
                voice_terms=()) -> list[dict]:
    """Route every unprocessed edit and open a proposal for each.

    Returns the revised event lines to append. Already-processed events
    are skipped, so running the learner twice over the same record
    proposes nothing new — the convergence property that lets it run on
    a schedule without a human watching."""
    from engine.flywheel.proposals import ProposalStore

    proposals = ProposalStore(store.root)
    revised = []
    for event in events:
        if event.get("kind") != "edit" or is_processed(event):
            continue
        reason = infer_edit_reason(event, voice_terms=voice_terms)
        target = route_of(reason)
        if target == "none":
            revised.append(revised_event(
                event, target="none",
                action_taken="no route for this edit reason", at=at))
            continue
        source = {"door": "flywheel", "pursuit_id": event["pursuit_id"],
                  "event_ids": [event["event_id"]]}
        if event.get("section_id"):
            source["section_id"] = event["section_id"]
        if event.get("actor_role") == "external_reviewer":
            source["external"] = True
        proposal = proposals.open(
            source=source, target=target,
            kind=_KIND_FOR_TARGET[target], at=at,
            diff={"text": {"before": event.get("before"),
                           "after": event.get("after")}},
            note=(f"A reviewer edit classified {reason!r} suggests the "
                  f"{target.replace('_', ' ')} is out of date here."))
        revised.append(revised_event(
            event, target=target,
            action_taken=f"proposal:{proposal['proposal_id']}", at=at))
    return revised


_KIND_FOR_TARGET = {
    "fact_sheet": "update_card",
    "corpus": "update_card",
    "voice_spec": "voice_spec_change",
    "playbook": "playbook_note",
    "validation_tuning": "validation_tuning_note",
}
