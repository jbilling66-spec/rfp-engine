"""Steward notes — the read model over ACCEPTED proposals (P26c, P1-43).

A voice-spec, playbook or validation-tuning proposal, or an edit whose
section cited no firm card, has no card to land on. Its home is the
accepted proposal itself: the steward's decision, the diff the human
wrote, and the events it came from are already one validated record
under kb/proposals/. This module projects those records by target so
the drafter (playbook + voice_spec, engine/drafting) and the KB screen
read the same thing — one home, no second copy to drift, nothing new
for the anonymization harness or the purge to learn about.

The decision NOT to materialize a notes file is recorded in B116 §4b
with its reopening trigger.
"""

from pathlib import Path

NOTE_KINDS = ("voice_spec_change", "playbook_note", "validation_tuning_note")


_KEY_ORDER = ("comment", "agent_reply", "claim", "waiver_reason", "text")


def _text_of(proposal: dict) -> str:
    """The human's words in the diff — after-strings only (a note is
    what the reviewer said, not what the draft used to say) — in READING
    order: the comment before the agent's reply, the claim before the
    reason (the record stores keys sorted, which put the reply first —
    caught on the P26c walk, B117 §4)."""
    diff = proposal.get("diff") or {}
    keys = [k for k in _KEY_ORDER if k in diff] + sorted(
        k for k in diff if k not in _KEY_ORDER)
    parts = []
    for key in keys:
        change = diff[key]
        if isinstance(change, dict) and change.get("after"):
            parts.append(" ".join(str(change["after"]).split()))
    return " — ".join(parts)


def is_note(proposal: dict) -> bool:
    kind = proposal.get("kind")
    return kind in NOTE_KINDS or (kind == "update_card"
                                  and not proposal.get("kb_id"))


def read_notes(kb_root, targets=("playbook", "voice_spec"), *,
               limit: int | None = 20) -> list[dict]:
    """Accepted notes under `targets`, oldest first, the last `limit`
    kept (the drafter's prompt prefix must not grow without bound —
    B116 §4f). Each: note_id (the proposal id), target, at/by (the
    steward's decision), pursuit_id, event_ids, external, text, note."""
    from engine.flywheel.proposals import ProposalStore

    wanted = set(targets)
    out = []
    for proposal in ProposalStore(Path(kb_root)).list(status="accepted"):
        if proposal.get("target") not in wanted or not is_note(proposal):
            continue
        decided = proposal.get("decided") or {}
        source = proposal.get("source") or {}
        out.append({
            "note_id": proposal["proposal_id"],
            "target": proposal["target"],
            "at": decided.get("at", proposal.get("created")),
            "by": decided.get("by", ""),
            "pursuit_id": source.get("pursuit_id"),
            "event_ids": list(source.get("event_ids") or []),
            "external": bool(source.get("external")),
            "text": _text_of(proposal),
            "note": proposal.get("note", ""),
        })
    out.sort(key=lambda n: (n["at"] or "", n["note_id"]))
    return out[-limit:] if limit else out


def render_notes(notes: list[dict]) -> str:
    """The prompt lines: `- [target] text` — the human's words, nothing
    generated (zero-spend v1, B116 §4)."""
    return "\n".join(f"- [{n['target'].replace('_', ' ')}] {n['text']}"
                     for n in notes if n["text"])


def steward_notes_frame(store, targets=("playbook", "voice_spec"), *,
                        limit: int = 20) -> str:
    """The prompt block the drafter and the reviser carry after the
    voice spec (B116 §4f): the last `limit` accepted playbook + voice
    notes, firm-framed. Empty when there are none — the prompt is then
    byte-identical to before P26c."""
    from engine.kb.lanes import as_lanes
    from engine.llm.frames import wrap_steward_notes

    rendered = render_notes(read_notes(as_lanes(store).firm.root, targets,
                                       limit=limit))
    return wrap_steward_notes(rendered) if rendered else ""
