"""Whitelist-parse of the drafter's wire — model proposes, code writes
(B22(3) lineage), reconciled by slot_id and never by position (v1
lesson: order untrusted, count untrusted).

Failure asymmetry (B31(2)): an unparseable DRAFT wire raises WireError
and the caller pends the section (the run continues — thirty-nine good
sections and one named pend beat a failed job); an unparseable CHECK
wire fails OPEN — the check is an improver, and destroying a valid
draft because its reviewer rambled would invert the loop's purpose.

Citation gate (B31(1), the v1 RAG ban's teeth): a kb_id outside the
cards opened for THIS section is removed-and-reported — it never
reaches cards_cited, so emit_kb_retrieval's cited ⊆ opened invariant
holds by construction.
"""

import json

from engine.contracts import check_prose


def _clean_prose(text: str, where: str) -> str:
    """P26a Group B (P2-29b): a control character in model prose is a
    WireError here — the section pends with the reason (a named pend
    beats a failed job) and the envelope never carries a byte python-docx
    would refuse at the exit door hours later."""
    bad = check_prose(text)
    if bad:
        raise WireError(f"{where}: {bad}")
    return text


class WireError(ValueError):
    """The draft wire was unusable; the section pends with this reason."""


def _clean_kb_ids(raw, opened_ids: set[str], where: str,
                  warnings: list[str]) -> list[str]:
    if not isinstance(raw, list):
        if raw is not None:
            warnings.append(f"{where}: kb_ids not a list; dropped")
        return []
    out: list[str] = []
    for kb_id in raw:
        if kb_id in out:
            continue  # silent dedupe, order-preserving (B22(3) cites)
        if kb_id not in opened_ids:
            warnings.append(
                f"{where}: cited {kb_id!r} was not opened for this section; "
                "removed (cited ⊆ opened is a code gate, not a prompt rule)")
            continue
        out.append(kb_id)
    return out


def parse_wire_answers(text: str, *, requested: list[str],
                       opened_ids: set[str]
                       ) -> tuple[dict[str, dict], list[str]]:
    """-> ({slot_id: {prose, kb_ids}}, warnings). Missing requested slots
    are the CALLER's pend decision — this returns only what landed."""
    warnings: list[str] = []
    try:
        wire = json.loads(text)
    except json.JSONDecodeError as e:
        raise WireError(f"unparseable draft wire: {e}")
    answers = wire.get("answers") if isinstance(wire, dict) else None
    if not isinstance(answers, list):
        raise WireError("draft wire carries no answers list")

    requested_set = set(requested)
    out: dict[str, dict] = {}
    for i, entry in enumerate(answers):
        if not isinstance(entry, dict) or not entry.get("slot_id") \
                or not isinstance(entry.get("prose"), str):
            warnings.append(f"answers[{i}]: malformed entry dropped")
            continue
        slot_id = entry["slot_id"]
        if slot_id not in requested_set:
            warnings.append(f"answers[{i}]: slot {slot_id!r} was not "
                            "requested; dropped")
            continue
        if slot_id in out:
            warnings.append(f"answers[{i}]: duplicate slot {slot_id!r}; "
                            "first wins, duplicate dropped")
            continue
        out[slot_id] = {
            "prose": _clean_prose(entry["prose"], f"answers[{i}] ({slot_id})"),
            "kb_ids": _clean_kb_ids(entry.get("kb_ids"), opened_ids,
                                    f"answers[{i}] ({slot_id})", warnings),
        }
    return out, warnings


def parse_wire_prose(text: str, *, opened_ids: set[str]
                     ) -> tuple[dict, list[str]]:
    """Path B: -> ({prose, kb_ids}, warnings)."""
    warnings: list[str] = []
    try:
        wire = json.loads(text)
    except json.JSONDecodeError as e:
        raise WireError(f"unparseable draft wire: {e}")
    if not isinstance(wire, dict) or not isinstance(wire.get("prose"), str):
        raise WireError("draft wire carries no prose")
    return {
        "prose": _clean_prose(wire["prose"], "prose"),
        "kb_ids": _clean_kb_ids(wire.get("kb_ids"), opened_ids, "prose",
                                warnings),
    }, warnings


def parse_wire_check(text: str, *, requested: list[str] | None,
                     opened_ids: set[str]) -> tuple[str, object, list[str]]:
    """-> (verdict, replacement, warnings); verdict 'pass' | 'fixed'.
    replacement is answers-by-slot (Path A) or a prose dict (Path B),
    None on pass. EVERY failure path returns ('pass', None, warning) —
    fail open, keep the draft."""
    warnings: list[str] = []
    try:
        wire = json.loads(text)
    except json.JSONDecodeError as e:
        return "pass", None, [f"check wire unparseable ({e}); draft kept"]
    verdict = wire.get("verdict") if isinstance(wire, dict) else None
    if verdict == "pass":
        return "pass", None, warnings
    if verdict != "fixed":
        return "pass", None, [f"check verdict {verdict!r} unknown; draft kept"]
    try:
        if requested is not None:
            replacement, fix_warnings = parse_wire_answers(
                text, requested=requested, opened_ids=opened_ids)
        else:
            replacement, fix_warnings = parse_wire_prose(
                text, opened_ids=opened_ids)
    except WireError as e:
        return "pass", None, [f"check fix malformed ({e}); draft kept"]
    return "fixed", replacement, warnings + fix_warnings
