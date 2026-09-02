"""Gap pings (B37/D14/D15): the async 2-line questions, never a
blocking SME queue (G6). `pings/pings.jsonl` is append-only; a ping's
answer is a NEW line for the same ping_id (last-wins fold, the jobs-
journal pattern).

Escalation is COMPUTED at read time against the request's `at` (>24h
unanswered => escalated, alert route_to pursuit_lead) — no stored
escalation state, no sweep job, byte-deterministic, and the frozen
acceptance clause tests it on an injected clock. The notifier seam is a
protocol with the in-app inbox as its only P9 sink: the channel choice
(email/Teams) is the owner's named pre-pilot homework (N4/G3), and the seam
is what makes that choice config, not surgery.

Ping/answer actions emit run-log `gap` lines carrying pinged_at /
answered_at / resolution — the dormant schema fields (B28(12)) get
their writers here — and flip the LIVE plan's gap status (the
live-copy-vs-record pattern; the frozen plan never moves).
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from engine.contracts import append_fsync, read_jsonl

ESCALATION_HOURS = 24  # N4: unanswered past this => escalate


class PingError(ValueError):
    """A rule said no — maps to 4xx at the route."""


def _parse(at: str) -> datetime:
    """Naive strings are the server's own UTC clock (no suffix); aware
    strings carry Z or an offset. Both normalize to aware UTC so an age
    can always be computed (P2-48: one aware record used to 500 the
    whole cross-pursuit inbox)."""
    parsed = datetime.fromisoformat(at.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class PingLane:
    def __init__(self, pursuit):
        self.pursuit = pursuit
        self.path = pursuit.root / "pings" / "pings.jsonl"

    def _append(self, line: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        append_fsync(self.path, json.dumps(line, sort_keys=True))  # M-31

    def _folded(self) -> dict[str, dict]:
        records, _torn = read_jsonl(self.path)  # P1-17: a torn tail tolerated
        out: dict[str, dict] = {}
        for line in records:
            out[line["ping_id"]] = {**out.get(line["ping_id"], {}), **line}
        return out

    # -- the live-document join --------------------------------------------

    def _live_gap(self, plan: dict, gap_id: str) -> tuple[dict, dict]:
        for section in plan.get("sections", []):
            for gap in section.get("gaps", []):
                if gap.get("gap_id") == gap_id:
                    return section, gap
        raise PingError(f"no gap {gap_id!r} in the live plan")

    def _find_gap(self, doc: dict, gap_id: str):
        """(section_id, gap, lane) over either live document. A PLAN
        carries sections[].gaps[]; a BRIEF carries intake.gaps[] (P15) —
        the join this lane could never make while intake gaps existed
        only as run-log lines."""
        if "sections" in doc:
            section, gap = self._live_gap(doc, gap_id)
            return section["section_id"], gap, "plan"
        for gap in doc.get("intake", {}).get("gaps", []):
            if gap.get("gap_id") == gap_id:
                return "intake", gap, "intake"
        raise PingError(f"no gap {gap_id!r} on the live document")

    def _refuse_if_frozen(self, lane: str) -> None:
        if lane == "intake" and (self.pursuit.root
                                 / "brief.frozen.json").exists():
            raise PingError(
                "intake gaps are settled once the brief freezes (Gate 1) "
                "— post-freeze corrections go through the redo/addendum "
                "lanes, never a quiet edit of a frozen record")

    # -- actions (each inside its caller's mini-run) -----------------------

    def ping(self, log, doc: dict, *, gap_id: str, route_to: str,
             at: str, actor: str) -> dict:
        section_id, gap, lane = self._find_gap(doc, gap_id)
        self._refuse_if_frozen(lane)
        if gap.get("status") not in ("open",):
            raise PingError(f"gap {gap_id} is {gap.get('status')!r} — only "
                            "an open gap pings")
        record = {"ping_id": f"png_{len(self._folded()) + 1:04d}",
                  "gap_id": gap_id, "section_id": section_id,
                  "question": gap.get("question_to_human", ""),
                  "route_to": route_to, "pinged_at": at, "by": actor}
        self._append(record)
        if lane == "plan":
            # the brief's status vocabulary has no "pinged" — an intake
            # gap stays open (the journal carries the routing) so gate_0
            # can still take its answer at decision time
            gap["status"] = "pinged"
        log.emit("gap", stage="review_loop", gap={
            # the intake lane carries the gap's OWN reason (P15); the
            # plan lane keeps its settled kb_empty vocabulary
            "gap_id": gap_id,
            "reason": gap.get("reason", "kb_empty") if lane == "intake"
            else "kb_empty",
            "question_to_human": record["question"],
            "pinged_at": at, "resolution": "unresolved",
        }, **({"target": {"section_id": section_id}} if lane == "plan"
              else {}))
        return record

    def answer(self, log, doc: dict, *, ping_id: str, answer: str,
               at: str, actor: str, propose_card: bool = False,
               kb_root=None) -> dict:
        folded = self._folded()
        record = folded.get(ping_id)
        if record is None:
            raise PingError(f"unknown ping {ping_id!r}")
        if record.get("answered_at"):
            raise PingError(f"ping {ping_id} already answered at "
                            f"{record['answered_at']}")
        if not answer.strip():
            raise PingError("an answer needs text")
        if propose_card and kb_root is None:
            # Validated UP FRONT so a refused request mutates nothing —
            # honored or refused, never dropped (gate.py's posture).
            raise PingError(
                "propose_card requested but no kb_root wired — the "
                "request must be honored or refused, never dropped")
        section_id, gap, lane = self._find_gap(doc, record["gap_id"])
        self._refuse_if_frozen(lane)
        update = {"ping_id": ping_id, "answered_at": at,
                  "resolution": "answered", "answered_by": actor,
                  # P1-36: the SME's TEXT lives on the append-only record
                  # too — the live plan/brief write that follows can fail,
                  # and a ping refuses to be answered twice
                  "answer": answer}
        self._append(update)
        gap["status"] = "answered"
        gap["answer"] = answer
        if lane == "intake":
            # the same fields gate_0's own answers stamp — one vocabulary.
            # The answer lands on the GAP, never auto-folded into a brief
            # field: field rewrites are gate_0 CORRECTIONS, which stamp
            # the assumption register — an auto-fold here would leave a
            # corrected field under an unconfirmed register entry.
            gap["answered_by"] = actor
            gap["answered_at"] = at
        proposal = None
        if propose_card:
            # P17/C11 (B72§5's deferral closed): the gate_0 gap→card
            # link extended to the ping lane — OPT-IN, through the
            # steward proposal door, never straight into the corpus
            # (B69§7). Same lane-agnostic spawner gate_0 uses.
            from pathlib import Path as _Path

            from engine.kb.curation import propose_gap_answer_card
            proposal = propose_gap_answer_card(
                _Path(kb_root), gap={**gap, "gap_id": record["gap_id"]},
                pursuit_id=self.pursuit.pursuit_id,
                operator=actor, at=at)
        log.emit("gap", stage="review_loop", gap={
            "gap_id": record["gap_id"],
            "reason": gap.get("reason", "kb_empty") if lane == "intake"
            else "kb_empty",
            "question_to_human": record["question"],
            "pinged_at": record["pinged_at"], "answered_at": at,
            "resolution": "answered",
        }, **({"target": {"section_id": section_id}} if lane == "plan"
              else {}))
        out = {**record, **update}
        if proposal:
            out["proposal"] = proposal  # steward inbox, not corpus
        return out

    def open_gap(self, log, plan: dict, *, section_id: str, question: str,
                 at: str, actor: str) -> dict:
        """Mid-review gap opening (D15/WP11): a reviewer can ASK — the
        gap lands on the live plan with a review-lane id and becomes
        draftable at the round after its answer."""
        section = next((s for s in plan.get("sections", [])
                        if s["section_id"] == section_id), None)
        if section is None:
            raise PingError(f"unknown section {section_id!r}")
        if not question.strip():
            raise PingError("a gap needs its question_to_human")
        existing = [g for s in plan.get("sections", [])
                    for g in s.get("gaps", [])
                    if "_review_" in g.get("gap_id", "")]
        gap_id = (f"gap_{self.pursuit.pursuit_id}_review_"
                  f"{len(existing) + 1:02d}")
        gap = {"gap_id": gap_id, "kind": "needs_sme",
               "question_to_human": question, "status": "open"}
        section.setdefault("gaps", []).append(gap)
        log.emit("gap", stage="review_loop", gap={
            "gap_id": gap_id, "reason": "needs_sme",
            "question_to_human": question, "resolution": "unresolved",
        }, target={"section_id": section_id})
        return gap

    # -- the inbox (read model; escalation computed HERE) ------------------

    def inbox(self, *, at: str) -> list[dict]:
        now = _parse(at)
        rows = []
        for record in self._folded().values():
            row = dict(record)
            if not record.get("answered_at"):
                age = now - _parse(record["pinged_at"])
                row["age_hours"] = round(age / timedelta(hours=1), 1)
                row["escalated"] = age > timedelta(hours=ESCALATION_HOURS)
                if row["escalated"]:
                    row["alert"] = {"condition": "gap_unanswered_past_"
                                                 "escalation_threshold",
                                    "severity": "warning",
                                    "route_to": "pursuit_lead"}
            rows.append(row)
        return sorted(rows, key=lambda r: r["ping_id"])


class Notifier:
    """The G3 seam: channel choice (email/Teams/in-app) is the owner's named
    pre-pilot homework; until then the in-app inbox IS the delivery and
    this records the intent honestly instead of pretending to send."""

    def notify(self, ping: dict) -> None:  # pragma: no cover - seam
        pass


def cross_pursuit_inbox(workspace: Path, *, at: str) -> list[dict]:
    from engine.workspace import PursuitDir
    rows = []
    for root in sorted(p for p in Path(workspace).iterdir()
                       if p.is_dir() and (p / "pings").is_dir()):
        lane = PingLane(PursuitDir(Path(workspace), root.name))
        for row in lane.inbox(at=at):
            rows.append({**row, "pursuit_id": root.name})
    return rows
