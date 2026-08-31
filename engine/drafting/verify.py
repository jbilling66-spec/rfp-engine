"""Code checks on final draft text (B31(8)): every envelope claim about
the text — flag presence, canonical fidelity, omission statements — is
scanned by code from the prose itself, never taken from the model's
wire. Violations are recorded findings, not blocks: P8's validation
stack owns enforcement, and a P7 block would front-run its calibration.

The honest-omission line (B31(7)) is code-composed and only where the
buyer instructed it (constraint flag state_if_not_offered): v1's lesson
stands — a model handed the refusal could soften an attested "no" into
marketing, so the model never sees the omitted slot at all.
"""

PROPOSED_FLAG = "[proposed approach]"

# Golden wording — buyer-facing; the owner blesses alongside the voice spec.
_OMISSION_TEMPLATE = ("Not offered: {topic}. We state capability boundaries "
                      "plainly rather than overstate scope.")


def normalize_ws(text: str) -> str:
    return " ".join(text.split())


def canonical_verified(body: str, text: str) -> bool:
    """Near-verbatim (B31(8)): the card body, whitespace-normalized,
    appears contiguously in the answer."""
    return normalize_ws(body) in normalize_ws(text)


def flag_present(text: str) -> bool:
    return PROPOSED_FLAG in text


def omission_line(slot: dict) -> str | None:
    """The code-composed honest-omission sentence — ONLY when the buyer
    instructed 'state if not offered'; otherwise the cell stays honestly
    empty for the human (P9 write-back) to leave or fill."""
    flags = slot.get("constraints", {}).get("flags", [])
    if "state_if_not_offered" not in flags:
        return None
    topic = (slot.get("question_text") or slot.get("ref_id")
             or slot.get("slot_id", "")).strip().rstrip("?.").strip()
    return _OMISSION_TEMPLATE.format(topic=topic)


def length_warnings(slot: dict, text: str) -> list[str]:
    """Warn-only at P7 (B31(14)); P8's validation stack enforces."""
    constraints = slot.get("constraints", {})
    out: list[str] = []
    max_words = constraints.get("max_words")
    if max_words is not None and len(text.split()) > max_words:
        out.append(f"slot {slot.get('slot_id')}: {len(text.split())} words "
                   f"exceeds max_words {max_words}")
    max_chars = constraints.get("max_chars")
    if max_chars is not None and len(text) > max_chars:
        out.append(f"slot {slot.get('slot_id')}: {len(text)} chars "
                   f"exceeds max_chars {max_chars}")
    return out
