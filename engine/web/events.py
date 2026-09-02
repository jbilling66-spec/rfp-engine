"""The feedback-events lane (B37/D5): `events/events.jsonl` is the
append-only record of COMPLETED interactions, schema-validated per line
before it lands. Comments and edits are PENDING (`events/pending.json`,
atomic rewrite, durable) until a revise round consumes them — the
finalized event then carries `comment_text` AND `agent_reply`, exactly
the shape the schema authored. Accept / reject / waive_block / outcome /
review_session append immediately: they are complete the moment they
happen.

Effort (D13): ONE event retains BOTH figures — `confirmed` requires
`active_ms` (the passive figure it was pre-filled from) alongside
`confirmed_minutes`; `manual` is the offline path (no passive figure to
retain); `passive` is the UI's own measurement. Outcome (D30): append-
only; the LATEST outcome wins at read — corrections are new events,
never edits to the record.

Vocabularies are read FROM the schema at import — one copy per rule
(v1's drifted-tuple lesson: "a stale copy matches nothing").
"""

import json
import os
import threading
from pathlib import Path

from engine.contracts import check_prose, validate
from engine.contracts.validate import SCHEMAS_DIR

_SCHEMA = json.loads(
    (SCHEMAS_DIR / "feedback-event.schema.json").read_text(encoding="utf-8"))
ACTOR_ROLES = tuple(_SCHEMA["properties"]["actor_role"]["enum"])
EVENT_KINDS = tuple(_SCHEMA["properties"]["kind"]["enum"])
EDIT_REASONS = tuple(_SCHEMA["properties"]["edit_reason"]["enum"])
OUTCOME_RESULTS = tuple(
    _SCHEMA["properties"]["outcome"]["properties"]["result"]["enum"])
EFFORT_SCOPES = tuple(
    _SCHEMA["properties"]["effort"]["properties"]["scope"]["enum"])
EFFORT_GATES = tuple(
    _SCHEMA["properties"]["effort"]["properties"]["gate"]["enum"])


_APPEND_LOCK = threading.Lock()  # one process; across processes: the workspace flock


def _next_event_n(events: list[dict]) -> int:
    """max(existing)+1 over real event ids — never a count (P1-20)."""
    seen = [int(e["event_id"][4:]) for e in events
            if str(e.get("event_id", "")).startswith("evt_")
            and str(e["event_id"])[4:].isdigit()]
    return (max(seen) + 1) if seen else 1


class EventsError(ValueError):
    """A rule said no — maps to 4xx at the route."""


class EventsLane:
    def __init__(self, pursuit):
        self.pursuit = pursuit
        self.events_path = pursuit.root / "events" / "events.jsonl"
        self.pending_name = "events/pending.json"

    # -- the record --------------------------------------------------------

    def read(self) -> list[dict]:
        if not self.events_path.exists():
            return []
        return [json.loads(line) for line in
                self.events_path.read_text(encoding="utf-8").splitlines()]

    def current_revision(self) -> int:
        path = self.pursuit.root / "drafts" / "draft.json"
        if not path.exists():
            return 0
        return json.loads(
            path.read_text(encoding="utf-8")).get("revision_n", 0)

    def append(self, kind: str, *, at: str, actor: str, actor_role: str,
               **fields) -> dict:
        if actor_role not in ACTOR_ROLES:
            raise EventsError(
                f"actor_role must be one of {ACTOR_ROLES}, got "
                f"{actor_role!r} — effort and cost aggregate by role, and "
                "an invented role would pool silently")
        # P25 item 3 (P1-20): the id is minted from the lane's MAX under a
        # process-wide lock and written in the same critical section —
        # `len(read())+1` from two request threads minted one id twice
        # into an append-only record.
        with _APPEND_LOCK:
            event = {"event_id": f"evt_{_next_event_n(self.read()):04d}",
                     "pursuit_id": self.pursuit.pursuit_id, "kind": kind,
                     "at": at, "actor": actor, "actor_role": actor_role,
                     "revision": self.current_revision()}
            event.update({k: v for k, v in fields.items() if v is not None})
            validate("feedback_event", event)
            self.events_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.events_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(event, sort_keys=True) + "\n")
                f.flush()
                os.fsync(f.fileno())
        return event

    def finalized_by_cid(self) -> dict[str, dict]:
        """cid -> the finalized comment/edit event (P1-14): a replayed
        round commit consults this before appending, so the append-only
        record carries each consumed pending item exactly once."""
        return {e["cid"]: e for e in self.read() if e.get("cid")}

    # -- the pending store (comments/edits await a round) ------------------

    def _read_pending(self) -> dict:
        path = self.pursuit.root / self.pending_name
        if not path.exists():
            return {"pending": [], "next_cid": 1}
        data = json.loads(path.read_text(encoding="utf-8"))
        data.setdefault("next_cid", len(data["pending"]) + 1)
        return data

    def pending(self) -> list[dict]:
        return self._read_pending()["pending"]

    def _write_pending(self, entries: list[dict],
                       next_cid: int | None = None) -> None:
        # the cid counter is MONOTONIC, never len-derived: pending
        # shrinks as rounds consume, and a reissued cid once aliased a
        # dismissed guest comment into a consumed internal one
        if next_cid is None:
            next_cid = self._read_pending()["next_cid"]
        self.pursuit.write_json(self.pending_name,
                                {"pending": entries, "next_cid": next_cid})

    def drop_pending(self, cids: set) -> None:
        data = self._read_pending()
        data["pending"] = [p for p in data["pending"]
                           if p["cid"] not in cids]
        self._write_pending(data["pending"], data["next_cid"])

    def add_pending(self, *, kind: str, section_id: str, actor: str,
                    actor_role: str, at: str, provenance: str = "internal",
                    slot_id: str | None = None, text: str | None = None,
                    before: str | None = None, after: str | None = None,
                    edit_reason: str | None = None, **extra) -> dict:
        if kind not in ("comment", "edit"):
            raise EventsError("pending entries are comments or edits — "
                              "other kinds append immediately")
        if kind == "comment" and not text:
            raise EventsError("a comment needs text")
        if kind == "edit" and (before is None or after is None):
            raise EventsError("an edit needs before AND after — the diff "
                              "is the signal edit_survival computes from")
        if edit_reason is not None and edit_reason not in EDIT_REASONS:
            raise EventsError(
                f"edit_reason must be one of {EDIT_REASONS}")
        if actor_role not in ACTOR_ROLES:
            raise EventsError(f"actor_role must be one of {ACTOR_ROLES}")
        for label, value in (("text", text), ("before", before),
                             ("after", after)):
            bad = check_prose(value) if value is not None else None
            if bad:
                # P26a Group B (P2-29b): a human edit is the one prose
                # path with no model in the loop — refused at the door,
                # never pended into the envelope
                raise EventsError(f"{label}: {bad}")
        data = self._read_pending()
        entries = data["pending"]
        entry = {"cid": f"cmt_{data['next_cid']:04d}", "kind": kind,
                 "provenance": provenance, "section_id": section_id,
                 "actor": actor, "actor_role": actor_role, "at": at,
                 "revision": self.current_revision()}
        for key, value in (("slot_id", slot_id), ("text", text),
                           ("before", before), ("after", after),
                           ("edit_reason", edit_reason)):
            if value is not None:
                entry[key] = value
        entry.update(extra)
        entries.append(entry)
        self._write_pending(entries, data["next_cid"] + 1)
        return entry

    def mark_pending(self, cid: str, **fields) -> dict:
        """Include/dismiss curation marks (D16d) — the affirmative human
        act, recorded with its actor on the pending record."""
        entries = self.pending()
        entry = next((e for e in entries if e["cid"] == cid), None)
        if entry is None:
            raise EventsError(f"no pending entry {cid!r}")
        entry.update(fields)
        self._write_pending(entries)
        return entry

    def remove_pending(self, cid: str) -> dict:
        entries = self.pending()
        keep = [e for e in entries if e["cid"] != cid]
        if len(keep) == len(entries):
            raise EventsError(f"no pending entry {cid!r}")
        removed = next(e for e in entries if e["cid"] == cid)
        self._write_pending(keep)
        return removed

    # -- read models -------------------------------------------------------

    def latest_outcome(self) -> dict | None:
        outcomes = [e for e in self.read() if e["kind"] == "outcome"]
        return outcomes[-1] if outcomes else None  # last-wins (D30)
