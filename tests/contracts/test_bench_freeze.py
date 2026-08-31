"""The bench contract is frozen (CLAUDE.md rule 3, spec rule 1's data-not-code
exception): schemas/target-slot.schema.json never changes. Instance validation
catches a NARROWING edit; a widening one (new optional property, relaxed enum)
passed silently until this pin (B30). Changing this digest requires the owner and a
DECISIONS.md entry — there is no legitimate in-phase reason for it to move.
"""

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FROZEN_SHA256 = "adafc4b059f4f058ab51a1193c624344edd63eb8f239e039311cbddeb841a34a"


def test_target_slot_schema_is_byte_frozen():
    digest = hashlib.sha256(
        (ROOT / "schemas" / "target-slot.schema.json").read_bytes()
    ).hexdigest()
    assert digest == FROZEN_SHA256, (
        "target-slot.schema.json changed — the bench contract is frozen "
        "(CLAUDE.md rule 3). If the owner approved a change, record it in "
        "DECISIONS.md and re-pin."
    )
