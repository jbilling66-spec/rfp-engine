"""Prompt assembly for the Section Drafter (B31): code renders every
context surface, the model never sees a raw artifact.

Trust framing per input (THREAT_MODEL boundary): the voice spec is firm
(trusted column) via the eighth frame; the brief digest reuses the
planning renderer wrap_brief_context'd (one renderer — a format change
fails planning and drafting fixtures together, never silently apart);
slot question text is RAW BUYER TEXT and gets the S1 untrusted frame —
drafting is the first stage that ever puts it in a model prompt; KB
card bodies ride wrap_kb_card; the pursuit lead's Gate-2 dispositions
ride wrap_lead_context (firm steering, the ramble precedent).

The section directive is code-composed firm text: SLOT lines,
constraint instructions (v1 lesson: stated as instructions, not a data
dump), canonical and flagged-drafting demands, and the wire-shape
reminder. Its line formats are the derive-wire fixture's parse targets.
"""

import re
from pathlib import Path

from engine.llm.frames import (
    wrap_brief_context,
    wrap_lead_context,
    wrap_untrusted,
    wrap_voice_spec,
)
from engine.planning.outline import brief_digest

ROOT = Path(__file__).resolve().parents[2]
VOICE_DEFAULT = ROOT / "config" / "voice-spec.md"

_H1 = "# Firm voice spec"
_NUMBERED = re.compile(r"^\s*\d+\.", re.M)


class VoiceSpecError(ValueError):
    """The voice spec is firm config: malformed or missing raises loud
    (manifest/reference loader precedent), it is not a refusal record."""


def load_voice_spec(path: Path = VOICE_DEFAULT) -> str:
    """Loader-is-the-contract (B28(9) pattern): H1 pinned, a non-empty
    numbered ## Principles list required. Extra ## sections tolerated —
    the P8 enrichments land without a code change (B31(13))."""
    if not path.exists():
        raise VoiceSpecError(f"voice spec missing: {path}")
    text = path.read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines or lines[0].strip() != _H1:
        raise VoiceSpecError(f"voice spec must open with {_H1!r}")
    _, sep, principles = text.partition("## Principles")
    if not sep or not _NUMBERED.search(principles.split("## ", 1)[0]):
        raise VoiceSpecError(
            "voice spec needs a non-empty numbered '## Principles' list")
    return text


def question_frame(slot: dict) -> str:
    """The slot's buyer-authored ask, S1-framed. sub_questions are buyer
    text too — they belong inside the frame, never in the directive."""
    parts = [slot.get("question_text", "").strip()]
    for sub in slot.get("sub_questions", []):
        parts.append(f"- {sub}")
    return wrap_untrusted(f"slot:{slot['slot_id']}",
                          "\n".join(p for p in parts if p))


def dispositions_block(steering: list[dict]) -> str:
    """Gate-2 dispositions as firm steering (wrap_lead_context — the
    ramble precedent). answered = content to use; reframed = a direction
    to execute (no automatic flag — B31(7))."""
    lines = ["Gate-2 dispositions from the pursuit lead:"]
    for item in steering:
        if item["kind"] == "answered":
            lines.append(f"- {item['label']}: ANSWER PROVIDED — use this "
                         f"content: {item['text']}")
        elif item["kind"] == "reframed":
            lines.append(f"- {item['label']}: REFRAME DIRECTION — "
                         f"{item['text']}")
    return wrap_lead_context("\n".join(lines))


def _constraint_lines(slot: dict) -> list[str]:
    """Constraints stated as instructions (v1 drafter lesson). Only the
    drafting-relevant ones — write-back formats and the P8-deferred
    flags (disclose_partner_delivery, no_offshore) are not rendered."""
    constraints = slot.get("constraints", {})
    out: list[str] = []
    if constraints.get("brevity") == "terse":
        out.append("  be terse — no lengthy narrative")
    if constraints.get("max_words") is not None:
        out.append(f"  hard limit: {constraints['max_words']} words")
    if constraints.get("max_chars") is not None:
        out.append(f"  hard limit: {constraints['max_chars']} characters")
    if "state_if_not_offered" in constraints.get("flags", []):
        out.append("  if something asked for is not offered, state so plainly")
    if slot.get("answer_location") == "appendix":
        out.append("  content routes to an appendix; draft it standalone")
    return out


def section_directive(section: dict, model_slots: list[dict], *,
                      canonical_ids: list[str], flagged_slot_ids: list[str],
                      flag_section: bool, path: str,
                      canonical_bodies: dict[str, str] | None = None,
                      effort_allocation: str = "uniform") -> str:
    lines = [f"SECTION: {section['title']}"]
    if effort_allocation == "weighted" and section.get("requirement_refs"):
        # B33(3): weighting is a code-derived emphasis line, not a knob.
        # It says WHICH refs the buyer weighted and leaves depth to the
        # drafter — a length instruction here would let the plan quietly
        # overrule the slot's own word limit.
        lines.append("WEIGHTED: the buyer scores this section's "
                     "requirements explicitly — cover every listed ref "
                     "with its evidence rather than summarising.")
    if path == "A_designated":
        for slot in model_slots:
            ref = slot.get("ref_id") or slot["slot_id"]
            lines.append(f"SLOT {slot['slot_id']} | ref {ref}")
            lines.extend(_constraint_lines(slot))
    elif section.get("requirement_refs"):
        lines.append("Cover requirement refs: "
                     + ", ".join(section["requirement_refs"]))
    for kb_id in canonical_ids:
        lines.append(f"CANONICAL {kb_id}: reproduce that framed card's body "
                     "verbatim inside the answer that uses it, and cite its "
                     "kb_id.")
        if canonical_bodies and kb_id in canonical_bodies:
            # F3 conditioning (B37/D9): the exact required text sits
            # adjacent to the instruction — the P8 live run showed the
            # demand alone was not enough. The `CANONICAL <id>: ` line
            # prefix above is the fixture scripts' pinned parse target
            # and must not change.
            lines.append("The exact required text follows; reproduce it "
                         "verbatim:")
            lines.append(canonical_bodies[kb_id])
    if flagged_slot_ids:
        lines.append("FLAGGED DRAFTING for slots: "
                     + ", ".join(flagged_slot_ids)
                     + " — draft best-effort; mark every novel claim with "
                       "[proposed approach].")
    if flag_section:
        lines.append("FLAGGED DRAFTING for this section — draft best-effort; "
                     "mark every novel claim with [proposed approach].")
    if path == "A_designated":
        ids = ", ".join(s["slot_id"] for s in model_slots)
        lines.append('Return {"answers": [...]} with exactly these '
                     f"slot_ids: {ids}.")
    else:
        lines.append('Return {"prose": "...", "kb_ids": [...]}.')
    return "\n".join(lines)


def build_draft_prompt(*, voice_text: str, frozen_brief: dict,
                       model_slots: list[dict], card_frames: list[str],
                       steering: list[dict], directive: str) -> str:
    parts = ["Task: draft.", wrap_voice_spec(voice_text),
             wrap_brief_context(brief_digest(frozen_brief))]
    parts.extend(question_frame(slot) for slot in model_slots)
    parts.extend(card_frames)
    if steering:
        parts.append(dispositions_block(steering))
    parts.append(directive)
    return "\n\n".join(parts)


def build_check_prompt(section: dict, drafted: dict, *,
                       checklist: list[str], path: str) -> str:
    lines = ["Task: check.", f"SECTION: {section['title']}", ""]
    if path == "A_designated":
        for slot_id, answer in drafted.items():
            lines.append(f"SLOT {slot_id}:")
            lines.append(answer["prose"])
            lines.append("")
    else:
        lines.append("PROSE:")
        lines.append(drafted["prose"])
        lines.append("")
    lines.append("CHECKLIST — verify every item:")
    lines.extend(f"- {item}" for item in checklist)
    lines.append('Return {"verdict": "pass"} or the corrected full draft '
                 'in the draft wire shape plus "verdict": "fixed".')
    return "\n".join(lines)
