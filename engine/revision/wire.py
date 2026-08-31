"""The revision wire (B37/D7): the drafter's shapes plus `replies`.

Whitelist-gated like every wire: answers ⊆ the section's revisable
slots, kb_ids ⊆ opened (delegated to the drafting parsers — one
whitelist per rule), replies ⊆ this round's consumed comment ids;
everything else drops-and-reports. Scalar-JSON documents (the P8 live
lesson: models answer forced tools with literal `null`) degrade to a
WireError, never a crash — the section keeps its prior prose."""

import json

from engine.drafting import wire as draft_wire

WireError = draft_wire.WireError


def parse_replies(text: str, *, allowed_event_ids: set[str]
                  ) -> tuple[dict[str, str], list[str]]:
    """{event_id -> reply}. Unknown ids drop-and-report; malformed
    entries drop-and-report; a scalar document raises WireError (the
    caller pends the section)."""
    warnings: list[str] = []
    try:
        obj = json.loads(text[text.index("{"):text.rindex("}") + 1]
                         if "{" in text else text)
    except (ValueError, TypeError):
        raise WireError("revision wire is not a JSON object")
    if not isinstance(obj, dict):
        # json.loads accepts scalar documents — live behavior (P8/F8)
        raise WireError(f"revision wire is a JSON {type(obj).__name__}, "
                        "not an object")
    replies: dict[str, str] = {}
    for i, entry in enumerate(obj.get("replies", []) or []):
        if not isinstance(entry, dict):
            warnings.append(f"replies[{i}]: malformed entry dropped")
            continue
        event_id = entry.get("event_id")
        reply = entry.get("reply")
        if event_id not in allowed_event_ids:
            warnings.append(f"replies[{i}]: unknown event_id {event_id!r} "
                            "dropped — replies join only this round's "
                            "comments")
            continue
        if not isinstance(reply, str) or not reply.strip():
            warnings.append(f"replies[{i}]: empty reply dropped")
            continue
        if event_id in replies:
            warnings.append(f"replies[{i}]: duplicate reply for "
                            f"{event_id} dropped")
            continue
        replies[event_id] = reply.strip()
    return replies, warnings


def parse_revision_answers(text: str, *, revisable: list[str],
                           opened_ids: set[str]
                           ) -> tuple[dict, list[str]]:
    """Path A: {slot_id -> {prose, kb_ids}} for CHANGED slots only —
    the model may return a subset; slots outside the revisable set drop-
    and-report (delegates the per-answer whitelist to the drafting
    parser, then filters)."""
    # the drafting parser already returns only what landed — a subset is
    # the caller's decision, which is exactly revision's semantics
    drafted, warnings = draft_wire.parse_wire_answers(
        text, requested=revisable, opened_ids=opened_ids)
    return drafted, warnings


def parse_revision_prose(text: str, *, opened_ids: set[str]
                         ) -> tuple[dict, list[str]]:
    return draft_wire.parse_wire_prose(text, opened_ids=opened_ids)
