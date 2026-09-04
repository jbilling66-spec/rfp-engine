"""The Feedback Learner's routing step: an edit becomes a lesson with an
address.

KB_DESIGN's table is the map — factual edits go to the Fact Sheet or the
corpus, tone to the voice spec, length and structure and strategy to the
playbook. This module applies it, records the decision on the event
(flywheel_routing), and opens a proposal so a human sees the diff.
P26c (P1-44) widened the door from edits to comments (with the agent's
reply) and waivers, and pointed a lesson at the cards its section cited.

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

# P2-50 (P26b-2): number TOKENS in order, thousands separators dropped
# — the digit SET compared before, so 1,200→2,100, 2024→2042 and 12→21
# all read "no number changed" and routed nowhere.
_NUMERIC = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _numbers(text: str) -> list[str]:
    return [m.replace(",", "") for m in _NUMERIC.findall(text)]


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

    if _numbers(before) != _numbers(after):
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
    """The P10 door, kept for callers that route edits only: the widened
    door is route_feedback (P26c)."""
    return route_feedback(events, store, at=at, voice_terms=voice_terms)


def route_feedback(events: list[dict], store, *, at: str, voice_terms=(),
                   cited: dict | None = None, waivers: dict | None = None,
                   anonymize=None) -> list[dict]:
    """Route every unprocessed piece of HUMAN feedback and open a
    proposal for each (P26c, P1-44 — the owner's call at B115 §10: what
    the human said or built is carried forward, in the human's own
    words, for a steward to decide).

    * an EDIT routes by its (inferred or given) reason; with `cited`
      ({section_id: [kb_id]} from the pursuit's production cite lines)
      a fact-sheet/corpus lesson opens ONE proposal PER cited firm card,
      each carrying the kb_id it lands on; no cite → one proposal with
      no kb_id, which lands as a note under the target;
    * a COMMENT (with its agent reply) routes to its edit_reason's
      target when the reviewer gave one, else to the playbook — an
      instruction to the revision agent is drafting guidance; an
      external comment WITHOUT a reply was dismissed (D16d) and is
      recorded as routed nowhere;
    * a WAIVE_BLOCK routes to validation tuning with the waiver's reason
      and the claim's text, supplied in `waivers` ({(actor, at): [claim]}
      from the annotated draft — the event carries neither); one
      proposal per matched claim.

    Every string a proposal carries passes through `anonymize` (identity
    by default; the accept door passes the pursuit's buyer identifiers
    → placeholders, so pursuit prose never lands on a firm card raw).

    Returns the revised event lines to append. Already-processed events
    are skipped, so running the learner twice over the same record
    proposes nothing new — the convergence property that lets it run on
    a schedule without a human watching."""
    from engine.flywheel.proposals import ProposalStore

    proposals = ProposalStore(store.root)
    cited = cited or {}
    waivers = waivers or {}
    clean = anonymize or (lambda text: text)
    revised = []
    for event in events:
        kind = event.get("kind")
        if is_processed(event) or kind not in ("edit", "comment",
                                               "waive_block"):
            continue
        if kind == "edit":
            revised.append(_route_edit(event, store, proposals, at=at,
                                       voice_terms=voice_terms,
                                       cited=cited, clean=clean))
        elif kind == "comment":
            revised.append(_route_comment(event, proposals, at=at,
                                          clean=clean))
        else:
            revised.append(_route_waiver(event, proposals, at=at,
                                         waivers=waivers, clean=clean))
    return revised


def _source(event: dict) -> dict:
    source = {"door": "flywheel", "pursuit_id": event["pursuit_id"],
              "event_ids": [event["event_id"]]}
    if event.get("section_id"):
        source["section_id"] = event["section_id"]
    if event.get("actor_role") == "external_reviewer":
        source["external"] = True
    return source


def _clean_or_none(clean, value):
    return None if value is None else clean(value)


def _route_edit(event, store, proposals, *, at, voice_terms, cited, clean):
    reason = infer_edit_reason(event, voice_terms=voice_terms)
    target = route_of(reason)
    if target == "none":
        return revised_event(
            event, target="none",
            action_taken="no route for this edit reason", at=at)
    kind = _KIND_FOR_TARGET[target]
    text = {"before": _clean_or_none(clean, event.get("before")),
            "after": _clean_or_none(clean, event.get("after"))}
    note = (f"A reviewer edit classified {reason!r} suggests the "
            f"{target.replace('_', ' ')} is out of date here.")
    # the cards this section actually drew on — the lesson lands on each
    kb_ids = [kb_id for kb_id in sorted(set(cited.get(
        event.get("section_id"), ()))) if store.card_exists(kb_id)]
    opened = []
    if kind == "update_card" and kb_ids:
        for kb_id in kb_ids:
            proposal = proposals.open(
                source=_source(event), target=target, kind=kind, at=at,
                kb_id=kb_id, diff={"text": text},
                note=f"{note} The section cited {kb_id}.")
            opened.append(proposal["proposal_id"])
    else:
        proposal = proposals.open(
            source=_source(event), target=target, kind=kind, at=at,
            diff={"text": text}, note=note)
        opened.append(proposal["proposal_id"])
    return revised_event(event, target=target,
                         action_taken="proposal:" + ",".join(opened), at=at)


def _route_comment(event, proposals, *, at, clean):
    text = event.get("comment_text")
    if not text:
        return revised_event(event, target="none",
                             action_taken="a comment without text", at=at)
    if (event.get("actor_role") == "external_reviewer"
            and not event.get("agent_reply")):
        # D16d: a dismissed guest comment finalizes without a reply — it
        # is on the record, and it is not the firm's lesson.
        return revised_event(event, target="none",
                             action_taken="dismissed external comment",
                             at=at)
    reason = event.get("edit_reason")
    target = route_of(reason) if reason else "playbook"
    if target == "none":
        target = "playbook"
    diff = {"comment": {"after": clean(text)}}
    if event.get("agent_reply"):
        diff["agent_reply"] = {"after": clean(event["agent_reply"])}
    where = (f" on section {event['section_id']}"
             if event.get("section_id") else "")
    note = (f"A reviewer comment{where}"
            + (f" classified {reason!r}" if reason else "")
            + f" — carried as {target.replace('_', ' ')} guidance in the "
              f"reviewer's own words.")
    proposal = proposals.open(
        source=_source(event), target=target,
        kind=_KIND_FOR_TARGET[target], at=at, diff=diff, note=note)
    return revised_event(event, target=target,
                         action_taken=f"proposal:{proposal['proposal_id']}",
                         at=at)


def _route_waiver(event, proposals, *, at, waivers, clean):
    matched = list(waivers.get((event.get("actor"), event.get("at"))) or ())
    if event.get("section_id"):
        matched = [c for c in matched
                   if c.get("section_id") in (None, event["section_id"])]
    if not matched:
        return revised_event(event, target="none",
                             action_taken="no waived claim found", at=at)
    opened = []
    for claim in matched:
        diff = {"waiver_reason": {"after": clean(claim.get("waiver_reason") or "")},
                "claim": {"after": clean(claim.get("text") or "")}}
        note = (f"A tier-{claim.get('tier')} block on section "
                f"{claim.get('section_id')} was waived — the reason is "
                f"validation-tuning evidence in the waiver's own words.")
        proposal = proposals.open(
            source=_source(event), target="validation_tuning",
            kind="validation_tuning_note", at=at, diff=diff, note=note)
        opened.append(proposal["proposal_id"])
    return revised_event(event, target="validation_tuning",
                         action_taken="proposal:" + ",".join(opened), at=at)


_KIND_FOR_TARGET = {
    "fact_sheet": "update_card",
    "corpus": "update_card",
    "voice_spec": "voice_spec_change",
    "playbook": "playbook_note",
    "validation_tuning": "validation_tuning_note",
}
