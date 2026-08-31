"""Slot-contract helpers shared by parsing, planning, and drafting.

THE CONTRACT OWNS THESE (v1 placement lesson — the v1 repo's
engine/contracts/slots.py): `field_key` is a join, not a formatting
choice — a slot parsed by the xlsx reader and one parsed by a docx
reader must agree on the key for the same label. `is_organizational` is
the one definition of "takes no response" that the planner and the P7
drafter must share; if they ever disagreed, the planner would spend
atoms on a slot the drafter never fills.
"""

import re

_KEY = re.compile(r"[^a-z0-9]+")


def field_key(label: str) -> str:
    """Deterministic join key for a response-field label."""
    key = _KEY.sub("_", label.lower()).strip("_")
    return key[:30] or "field"


def unique_keys(labels: list[str]) -> list[str]:
    """field_key per label, deterministically suffixed on collision —
    two 30-char-truncated labels colliding was a real v1 near-miss
    (application_vendor vs application_vendor_tools_funct)."""
    seen: dict[str, int] = {}
    out = []
    for label in labels:
        key = field_key(label)
        if key in seen:
            seen[key] += 1
            key = f"{key}_{seen[key]}"
        else:
            seen[key] = 1
        out.append(key)
    return out


def is_organizational(slot: dict) -> bool:
    """True for slots that take NO response (headers, shape 'none')."""
    return bool(slot.get("is_header")) or slot.get("response_shape") == "none"
