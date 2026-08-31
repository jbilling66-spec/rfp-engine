"""Coverage + Consistency (B34(7,8)) — code-first, model-assisted only
where code cannot judge.

Coverage RECOMPUTES every property from the delivered prose and the slot
container — never by parsing P7's warning strings (two implementations of
one rule drifting apart was v1's most-repeated defect; here the drafting
warnings are advisory and coverage's recomputation is the enforcement).
Length is measured on DELIVERED text with the [proposed approach] marker
stripped: v1 paid live for counting review machinery against the buyer's
cap. disclose_partner_delivery / no_offshore get a review-disposition
finding naming the obligation — deterministic content verification is
impossible and inventing one would violate spec rule 5.

Consistency: cross_refs resolve in code (a reference into a section that
never drafted is a defect no model needs to find); one mid-tier call
scans the labeled prose for contradictions, ids whitelisted, each
surviving contradiction flagging BOTH sections. Everything here flags or
reviews; nothing blocks (Q2 — the choke point enforces it anyway).
"""

import json

from engine.drafting.verify import (
    PROPOSED_FLAG,
    canonical_verified,
    flag_present,
    normalize_ws,
    omission_line,
)
from engine.validation.findings import Finding, make_finding

SUBQ_TASK = "Task: check sub-questions."
CONSISTENCY_TASK = "Task: check consistency."


def delivered_text(prose: str) -> str:
    """The buyer-visible words: review machinery stripped before any
    measurement (v1 markers.delivered_text lineage)."""
    return normalize_ws(prose.replace(PROPOSED_FLAG, " "))


def _length_findings(section_id, slot, prose) -> list[Finding]:
    constraints = slot.get("constraints") or {}
    text = delivered_text(prose)
    out = []
    words = len(text.split())
    max_words = constraints.get("max_words")
    if max_words and words > max_words:
        out.append(make_finding(
            check="coverage", rule="length_exceeded", disposition="review",
            message=f"{words} words exceeds max_words {max_words} "
                    f"(measured on delivered text, markers stripped)",
            section_id=section_id, slot_id=slot["slot_id"]))
    max_chars = constraints.get("max_chars")
    if max_chars and len(text) > max_chars:
        out.append(make_finding(
            check="coverage", rule="length_exceeded", disposition="review",
            message=f"{len(text)} characters exceeds max_chars {max_chars}",
            section_id=section_id, slot_id=slot["slot_id"]))
    return out


def coverage_findings(section_entry: dict, slots_by_id: dict[str, dict], *,
                      flagged_slots: frozenset[str] = frozenset(),
                      canonical_bodies: dict[str, str] | None = None
                      ) -> list[Finding]:
    """Deterministic coverage over one drafted section. flagged_slots =
    slot_ids Gate 2 demanded the [proposed approach] flag on (from the
    frozen plan's dispositions — the plan is the authority, not P7's
    envelope booleans)."""
    section_id = section_entry["section_id"]
    findings: list[Finding] = []

    for answer in section_entry.get("answers", []):
        slot = slots_by_id.get(answer["slot_id"])
        if slot is None:
            continue
        prose = answer.get("prose", "")
        if answer["status"] in ("pending", "awaiting_disposition"):
            findings.append(make_finding(
                check="coverage", rule="slot_unanswered", disposition="review",
                message=f"slot owed but {answer['status']} "
                        f"({answer.get('reason', 'no reason recorded')})",
                section_id=section_id, slot_id=answer["slot_id"]))
            continue
        if answer["status"] == "omitted":
            expected = omission_line(slot)
            if expected and normalize_ws(expected) not in normalize_ws(prose):
                findings.append(make_finding(
                    check="coverage", rule="omission_line_missing",
                    disposition="review",
                    message="state_if_not_offered demands the honest-omission "
                            "line and the recorded prose does not carry it",
                    section_id=section_id, slot_id=answer["slot_id"]))
            continue
        if answer["status"] != "drafted":
            continue
        findings.extend(_length_findings(section_id, slot, prose))
        if answer["slot_id"] in flagged_slots and not flag_present(prose):
            findings.append(make_finding(
                check="coverage", rule="flag_missing", disposition="review",
                message="Gate 2 demanded [proposed approach] on this slot "
                        "and the delivered prose does not carry it",
                section_id=section_id, slot_id=answer["slot_id"]))
        flags = (slot.get("constraints") or {}).get("flags", [])
        for obligation in ("disclose_partner_delivery", "no_offshore"):
            if obligation in flags:
                findings.append(make_finding(
                    check="coverage", rule="constraint_review",
                    disposition="review",
                    message=f"buyer instruction {obligation!r} applies — "
                            f"reviewer verifies the answer honors it "
                            f"(no deterministic check exists, spec rule 5)",
                    section_id=section_id, slot_id=answer["slot_id"]))

    # Path B section prose: length against any section-level constraint is
    # P9's (no slot carrier); canonical recompute below covers both paths.
    section_prose = " ".join(
        [section_entry.get("prose", "")]
        + [a.get("prose", "") for a in section_entry.get("answers", [])])
    for entry in section_entry.get("canonical", []):
        body = (canonical_bodies or {}).get(entry["kb_id"])
        if body is not None and not canonical_verified(body, section_prose):
            findings.append(make_finding(
                check="coverage", rule="canonical_violated",
                disposition="review",
                message=f"canonical block {entry['kb_id']} not reproduced "
                        f"near-verbatim (recomputed from prose)",
                section_id=section_id))
    return findings


def build_subq_prompt(section_title: str, question: str,
                      sub_questions: list[str], prose: str) -> str:
    numbered = "\n".join(f"{i}. {q}" for i, q in enumerate(sub_questions))
    return (f"{SUBQ_TASK}\n\nSection: {section_title}\n"
            f"Question: {question}\nSub-questions:\n{numbered}\n\n"
            f"ANSWER PROSE:\n{prose}\n\n"
            f'Return JSON only: {{"addressed": [{{"index": 0, '
            f'"addressed": true}}]}} — one entry per sub-question index.')


def parse_subq_wire(text: str, *, section_id: str, slot_id: str,
                    n: int) -> list[Finding]:
    """Any unaddressed index -> a review finding. An unparseable wire is a
    review finding too — 'not assessed' must draw eyes, never read as pass
    (the three-state lesson: None is not a pass)."""
    try:
        rows = json.loads(text)["addressed"]
        assert isinstance(rows, list)
    except (ValueError, KeyError, AssertionError, TypeError):
        return [make_finding(
            check="coverage", rule="sub_question_unaddressed",
            disposition="review",
            message="sub-question addressal could not be assessed "
                    "(unparseable wire) — not a pass",
            section_id=section_id, slot_id=slot_id)]
    findings = []
    for row in rows:
        index = row.get("index") if isinstance(row, dict) else None
        if not isinstance(index, int) or not 0 <= index < n:
            continue  # unknown index: dropped (nothing to anchor a finding to)
        if row.get("addressed") is not True:
            findings.append(make_finding(
                check="coverage", rule="sub_question_unaddressed",
                disposition="review",
                message=f"sub-question {index} not addressed in the answer",
                section_id=section_id, slot_id=slot_id))
    return findings


def cross_ref_findings(sections: list[dict], slots_by_id: dict[str, dict]
                       ) -> list[Finding]:
    """Code half of consistency: a cross_ref pointing at a ref whose slot
    never drafted (omitted/pending section or slot) is a dangling promise
    in the buyer's own numbering."""
    status_by_ref: dict[str, str] = {}
    for section in sections:
        for answer in section.get("answers", []):
            slot = slots_by_id.get(answer["slot_id"]) or {}
            ref = slot.get("ref_id") or answer.get("ref_id")
            if ref:
                status_by_ref[ref] = answer["status"]
    findings = []
    for section in sections:
        for answer in section.get("answers", []):
            slot = slots_by_id.get(answer["slot_id"]) or {}
            for ref in slot.get("cross_refs", []):
                target_status = status_by_ref.get(ref)
                if target_status is None or target_status not in (
                        "drafted", "gated_skipped"):
                    findings.append(make_finding(
                        check="consistency", rule="cross_ref_dangling",
                        disposition="review",
                        message=f"answer references {ref} which "
                                f"{'does not exist' if target_status is None else f'is {target_status}'}",
                        section_id=section["section_id"],
                        slot_id=answer["slot_id"]))
    return findings


def build_consistency_prompt(sections: list[tuple[str, str, str]]) -> str:
    """sections = (section_id, title, prose). One call over everything —
    contradiction is a cross-section property."""
    blocks = "\n\n".join(
        f"SECTION {section_id}: {title}\n{prose}"
        for section_id, title, prose in sections)
    return (f"{CONSISTENCY_TASK}\n\n{blocks}\n\n"
            f'Return JSON only: {{"contradictions": [{{"section_ids": '
            f'["<id>", "<id>"], "detail": "<the contradicting statements>"}}]}}'
            f" — empty list if none.")


def parse_consistency_wire(text: str, *, known_ids: frozenset[str]
                           ) -> tuple[list[Finding], list[str]]:
    """Whitelisted ids only; each surviving contradiction flags BOTH
    sections (same rule, both anchors — dedupe keys on section)."""
    warnings: list[str] = []
    try:
        rows = json.loads(text)["contradictions"]
        assert isinstance(rows, list)
    except (ValueError, KeyError, AssertionError, TypeError):
        return [], ["consistency wire unparseable — cross-section scan "
                    "recorded as not-assessed"]
    findings = []
    for row in rows:
        ids = row.get("section_ids") if isinstance(row, dict) else None
        if not isinstance(ids, list):
            warnings.append("malformed contradiction row dropped")
            continue
        valid = [i for i in ids if i in known_ids]
        if len(valid) < 2:
            warnings.append(
                f"contradiction with unknown section ids {ids!r} dropped")
            continue
        detail = str(row.get("detail", ""))[:400]
        for section_id in valid[:2]:
            findings.append(make_finding(
                check="consistency", rule="contradiction",
                disposition="review",
                message=f"contradicts {[i for i in valid[:2] if i != section_id][0]}: "
                        f"{detail}",
                section_id=section_id))
    return findings, warnings
