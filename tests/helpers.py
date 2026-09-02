"""Shared test-side workspace planting (P25 item 5).

`plant_freeze` writes a frozen artifact AND the gate checkpoint that
vouches for it, so a fixture exercises the real invariant — file and
checkpoint agree, and `read_frozen` verifies — instead of a back door.
`validate=False` (the default) keeps deliberately minimal synthetic
shapes past the schema, which is a TEST licence only: the engine's own
door, `PursuitDir.freeze_artifact`, always validates.
"""

import hashlib

from engine.workspace.pursuit import (
    ARTIFACT_FILES,
    FROZEN_FILES,
    FROZEN_GATES,
    _serialize,
)

GATE_FOR = FROZEN_GATES
LIVE_SHA_KEY = {"bid_brief": "brief_sha256", "pursuit_plan": "plan_sha256"}
PLANT_AT = "2026-08-09T09:00:00"


def plant_freeze(pursuit, kind: str, obj: dict, *, actor: str = "fixture",
                 at: str = PLANT_AT, validate: bool = False):
    """Plant `<kind>.frozen.json` plus its gate checkpoint. Returns
    (path, sha256). Re-planting overwrites (a fixture may stage several
    states); the engine door never does."""
    path = pursuit.root / FROZEN_FILES[kind]
    if validate:
        if path.exists():
            path.unlink()
        path, sha = pursuit.freeze_artifact(kind, obj)
    else:
        payload = _serialize(obj).encode("utf-8")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        sha = hashlib.sha256(payload).hexdigest()
    live_sha = pursuit.file_sha256(ARTIFACT_FILES[kind]) or sha
    pursuit.checkpoint(GATE_FOR[kind], {
        "decision": "approved", "actor": actor, "at": at,
        LIVE_SHA_KEY[kind]: live_sha, "frozen_sha256": sha})
    return path, sha


def plant_annotated(pursuit, *, blocked: bool = False, **fields):
    """Test-side minimal annotated draft bound to the LIVE envelope and
    freeze, packaging clear unless told — so a door's binding check
    passes for exactly what the fixture staged. Returns the path."""
    annotated = {
        "pursuit_id": pursuit.pursuit_id,
        "draft_sha256": pursuit.file_sha256("drafts/draft.json"),
        "plan_sha256": pursuit.file_sha256("plan.frozen.json"),
        "packaging": {"blocked": blocked,
                      "tier1_blocks": 1 if blocked else 0, "waived": 0},
        "sections": [],
        **fields,
    }
    path = pursuit.root / "drafts" / "annotated-draft.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_serialize(annotated), encoding="utf-8")
    return path
