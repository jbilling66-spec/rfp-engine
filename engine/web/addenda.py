"""The addendum lane (B37/D18, G4): buyer amendments arrive after the
freeze, and the engine's job is an honest IMPACT SCAN plus a human
decision — never a silent re-plan.

The scan is deterministic ADVISORY code (v1 diff.py's descendant): token
overlap between the addendum text and each section's title + slot
questions, ranked. No model call — the human decides what an amendment
means.

Two decisions: `note_only` routes the impacts into the review loop as
pending comments (the revise round consumes them like any reviewer
note); `replan` writes the live plan's `superseded` status (the enum's
FIRST writer), ARCHIVES the frozen plan into the addendum's folder
(moved intact, never rewritten — the record survives), clears the
planning checkpoints, and stores the addendum note as gate-2 redo
feedback — the NORMAL planning + Gate-2 lane then re-plans and
re-freezes, and every existing draft voids by plan_sha256 mismatch, not
by convention."""

import hashlib
import json
import re

_TOKEN = re.compile(r"[a-z0-9][a-z0-9-]{3,}")
_STOP = frozenset(
    "this that with from your will shall must have been they their the-firm "
    "response proposal section addendum amendment please provide include "
    "shall-be required requirements".split())


class AddendumError(ValueError):
    pass


def _tokens(text: str) -> set[str]:
    return {t for t in _TOKEN.findall(text.lower())} - _STOP


def scan_impact(addendum_text: str, plan: dict,
                slots_by_id: dict | None = None) -> list[dict]:
    needles = _tokens(addendum_text)
    impacts = []
    for section in plan.get("sections", []):
        haystack = section.get("title", "")
        for slot_id in section.get("slot_ids", []):
            slot = (slots_by_id or {}).get(slot_id, {})
            haystack += " " + slot.get("question_text", "")
        matched = sorted(needles & _tokens(haystack))
        if matched:
            impacts.append({"section_id": section["section_id"],
                            "score": len(matched),
                            "matched_terms": matched[:8]})
    return sorted(impacts, key=lambda i: (-i["score"], i["section_id"]))


class AddendumLane:
    def __init__(self, pursuit):
        self.pursuit = pursuit
        self.root = pursuit.root / "addenda"

    def store(self, *, filename: str, body: bytes, at: str,
              actor: str, slots_by_id: dict | None) -> dict:
        if not body:
            raise AddendumError("empty addendum upload")
        existing = sorted(p.name for p in self.root.glob("addm_*"))
        aid = f"addm_{len(existing) + 1:02d}"
        folder = self.root / aid
        folder.mkdir(parents=True)
        (folder / filename).write_bytes(body)
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError:
            text = ""
        plan = self.pursuit.read_artifact("plan.json")
        impacts = scan_impact(text, plan, slots_by_id) if text else []
        meta = {"addendum_id": aid, "filename": filename, "at": at,
                "by": actor, "impacts": impacts, "decision": None,
                "scanned": bool(text)}
        if not text:
            meta["note"] = ("binary upload — no text scan; the human "
                            "reads it directly")
        self.pursuit.write_json(f"addenda/{aid}/meta.json", meta)
        return meta

    def list(self) -> list[dict]:
        out = []
        for meta_path in sorted(self.root.glob("addm_*/meta.json")):
            out.append(json.loads(meta_path.read_text(encoding="utf-8")))
        return out

    def _meta(self, aid: str) -> dict:
        meta_path = self.root / aid / "meta.json"
        if not meta_path.exists():
            raise AddendumError(f"unknown addendum {aid!r}")
        return json.loads(meta_path.read_text(encoding="utf-8"))

    def decide(self, log, *, aid: str, decision: str, note: str,
               at: str, actor: str) -> dict:
        from engine.web.events import EventsLane
        meta = self._meta(aid)
        if meta.get("decision"):
            raise AddendumError(f"{aid} already decided: "
                                f"{meta['decision']!r}")
        if decision not in ("note_only", "replan"):
            raise AddendumError("decision must be note_only|replan")
        if decision == "note_only":
            # impacts become review-loop material: pending comments the
            # next revise round consumes like any reviewer note
            lane = EventsLane(self.pursuit)
            for impact in meta.get("impacts", []):
                lane.add_pending(
                    kind="comment", section_id=impact["section_id"],
                    actor=actor, actor_role="pursuit_lead", at=at,
                    text=(f"Addendum {aid} ({meta['filename']}) touches "
                          f"this section (terms: "
                          f"{', '.join(impact['matched_terms'])}). "
                          f"{note}".strip()))
        else:
            if not note.strip():
                raise AddendumError(
                    "replan requires a note — it becomes the redo "
                    "feedback the replan consumes")
            plan = self.pursuit.read_artifact("plan.json")
            plan["status"] = "superseded"  # the enum's first writer
            plan_path = self.pursuit.write_artifact("pursuit_plan", plan)
            log.emit("artifact", stage="gate_2", artifact={
                "kind": "pursuit_plan", "path": str(plan_path),
                "sha256": hashlib.sha256(
                    plan_path.read_bytes()).hexdigest()})
            frozen = self.pursuit.root / "plan.frozen.json"
            if frozen.exists():
                # archived intact — moved, never rewritten; the driver's
                # skip predicate now re-opens the planning lane
                frozen.rename(self.root / aid
                              / "plan.frozen.superseded.json")
            for stage in ("path_a_map", "path_b_outline", "pursuit_plan"):
                self.pursuit.clear_checkpoint(stage)
            # the redo-door carrier (gate.py's rejection pattern): the
            # replan reads this note as its feedback
            self.pursuit.checkpoint("gate_2", {
                "decision": "rejected", "actor": actor, "at": at,
                "notes": f"Addendum {aid} ({meta['filename']}): {note}",
                "plan_sha256": ""})
        meta.update({"decision": decision, "decided_by": actor,
                     "decided_at": at, "decision_note": note})
        self.pursuit.write_json(f"addenda/{aid}/meta.json", meta)
        return meta
