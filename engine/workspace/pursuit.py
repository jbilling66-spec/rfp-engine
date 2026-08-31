"""Pursuit workspace: one directory per pursuit, file-backed (standing rule 4;
dated — A5 moves persistence behind this seam, so keep the seam honest).

Artifacts are schema-validated and written atomically (tmp + rename) — a
half-written brief.json cannot exist. Stage checkpoints make resume real
(N2): a run that dies mid-pipeline restarts from its last completed stage
and produces the same artifacts as an uninterrupted run.
"""

import json
import os
import tempfile
from pathlib import Path

from engine.contracts import validate

SUBDIRS = ["drafts", "revisions", "events", "runs", "checkpoints", "inbox",
           "addenda", "pings", "share", "exports", "memory"]

ARTIFACT_FILES = {"bid_brief": "brief.json", "pursuit_plan": "plan.json"}


def _atomic_write_json(path: Path, obj: dict) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=2, sort_keys=True)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


class PursuitDir:
    def __init__(self, root: Path, pursuit_id: str):
        self.pursuit_id = pursuit_id
        self.root = Path(root) / pursuit_id
        for sub in SUBDIRS:
            (self.root / sub).mkdir(parents=True, exist_ok=True)

    # -- artifacts ---------------------------------------------------------

    def write_artifact(self, kind: str, obj: dict, name: str | None = None) -> Path:
        """Validate against the contract, then atomically write. Root
        artifacts (brief/plan) have fixed names; others need one."""
        validate(kind, obj)
        if name is None:
            name = ARTIFACT_FILES[kind]
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_json(path, obj)
        return path

    def read_artifact(self, name: str) -> dict:
        return json.loads((self.root / name).read_text(encoding="utf-8"))

    def write_json(self, name: str, obj: dict) -> Path:
        """Atomic JSON write for non-artifact workspace files. Callers
        validate content; this seam only guarantees atomicity and the
        deterministic serializer. (slots.json graduated to a registered
        contract kind at P9/E4 — B25's non-addition closed by B26's
        write-back dependency.)"""
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_json(path, obj)
        return path

    # -- checkpoints (N2) --------------------------------------------------

    def checkpoint(self, stage: str, payload: dict) -> None:
        _atomic_write_json(self.root / "checkpoints" / f"{stage}.json",
                           {"stage": stage, "payload": payload})

    def completed_stages(self) -> set[str]:
        return {p.stem for p in (self.root / "checkpoints").glob("*.json")}

    def checkpoint_payload(self, stage: str) -> dict:
        path = self.root / "checkpoints" / f"{stage}.json"
        return json.loads(path.read_text(encoding="utf-8"))["payload"]

    def clear_checkpoint(self, stage: str) -> None:
        """The one destructive workspace operation: only Gate-2 rejection
        calls it (redo-with-feedback — the cleared planning stages must
        genuinely rerun). Missing checkpoints are fine (idempotent)."""
        (self.root / "checkpoints" / f"{stage}.json").unlink(missing_ok=True)

    # -- runs --------------------------------------------------------------

    def new_run_id(self) -> str:
        existing = sorted(p.name for p in (self.root / "runs").iterdir()) if (
            self.root / "runs"
        ).exists() else []
        return f"run_{len(existing) + 1:04d}"

    def latest_run_id(self) -> str | None:
        runs = sorted(p.name for p in (self.root / "runs").iterdir())
        return runs[-1] if runs else None
