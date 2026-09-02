"""Pursuit workspace: one directory per pursuit, file-backed (standing rule 4;
dated — A5 moves persistence behind this seam, so keep the seam honest).

Artifacts are schema-validated and written atomically (tmp + rename) — a
half-written brief.json cannot exist. Stage checkpoints make resume real
(N2): a run that dies mid-pipeline restarts from its last completed stage
and produces the same artifacts as an uninterrupted run.
"""

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from engine.contracts import ContractError, validate

SUBDIRS = ["drafts", "revisions", "events", "runs", "checkpoints", "inbox",
           "addenda", "pings", "share", "exports", "memory"]

ARTIFACT_FILES = {"bid_brief": "brief.json", "pursuit_plan": "plan.json"}
# The frozen copies a gate writes (T7): one name per kind, written ONLY by
# freeze_artifact and moved ONLY by archive_frozen (P25 item 5, P0-2).
FROZEN_FILES = {"bid_brief": "brief.frozen.json",
                "pursuit_plan": "plan.frozen.json"}
# The gate whose checkpoint vouches for each freeze (`frozen_sha256`).
FROZEN_GATES = {"bid_brief": "gate_1", "pursuit_plan": "gate_2"}
# The one run-id shape (P25 item 3; the v1 P9-B3 "ONE copy of the regex"
# lesson, applied to runs): minted here and nowhere else.
RUN_ID = re.compile(r"^run_\d{4,}$")


def mint_run_id(runs_dir: Path) -> str:
    """The ONE run-id mint (P25 item 3, register P0-3): max(existing)+1
    over entries that ARE run ids — never a count, so a deleted middle
    run can never recycle an id into another run's audit trace, and a
    stray entry (`.DS_Store`, a notes folder) is never counted."""
    runs_dir = Path(runs_dir)
    existing = ([int(p.name[4:]) for p in runs_dir.iterdir()
                 if RUN_ID.fullmatch(p.name)] if runs_dir.exists() else [])
    return f"run_{(max(existing) + 1) if existing else 1:04d}"


def latest_run_id_in(runs_dir: Path) -> str | None:
    runs_dir = Path(runs_dir)
    existing = ([p.name for p in runs_dir.iterdir()
                 if RUN_ID.fullmatch(p.name)] if runs_dir.exists() else [])
    return max(existing, key=lambda n: int(n[4:])) if existing else None


def _serialize(obj: dict) -> str:
    """The one serializer: every workspace JSON file is these bytes, so a
    freeze written by the gate and a replay that re-serializes the same
    dict are byte-equal by construction."""
    return json.dumps(obj, indent=2, sort_keys=True) + "\n"


def _atomic_write_json(path: Path, obj: dict) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(_serialize(obj))
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

    # -- the two name rules every read/write honours -----------------------

    def _under_root(self, name: str) -> Path:
        """A workspace name resolves INSIDE this pursuit or refuses —
        `../other/brief.json` and absolute names never reach the disk
        (P25 item 5)."""
        path = self.root / name
        if not path.resolve().is_relative_to(self.root.resolve()):
            raise ContractError(
                f"{name!r} escapes the pursuit workspace {self.root}")
        return path

    @staticmethod
    def _refuse_frozen_name(name: str) -> None:
        if name.endswith(".frozen.json"):
            raise ContractError(
                f"{name!r}: a frozen file is written only by a gate through "
                "freeze_artifact and moved only by archive_frozen — never "
                "rewritten in place (T7; P25 item 5)")

    def write_artifact(self, kind: str, obj: dict, name: str | None = None) -> Path:
        """Validate against the contract, then atomically write. Root
        artifacts (brief/plan) have fixed names; others need one. Frozen
        names are refused here — freeze_artifact is the door."""
        if name is None:
            name = ARTIFACT_FILES[kind]
        self._refuse_frozen_name(name)
        validate(kind, obj)
        path = self._under_root(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_json(path, obj)
        return path

    def read_artifact(self, name: str) -> dict:
        return json.loads(self._under_root(name).read_text(encoding="utf-8"))

    # -- the freeze door (T7; P25 item 5, register P0-2) --------------------

    def freeze_artifact(self, kind: str, obj: dict) -> tuple[Path, str]:
        """Write the frozen copy a gate produces, and return its sha256.
        Idempotent-or-refuse: an existing freeze with the SAME bytes is
        returned untouched (the mid-gate crash replay converges here), an
        existing freeze with DIFFERENT bytes refuses — a freeze is never
        rewritten in place; Gate-2 rejection and the addendum replan are
        the redo doors, and archive_frozen is the one sanctioned move.

        Honest limit: this door guards engine code that uses the seam. A
        raw filesystem write bypasses it; the gate checkpoint's recorded
        `frozen_sha256`, verified by read_frozen, is the guard against
        that — tamper-EVIDENCE, not tamper-proofing."""
        validate(kind, obj)
        path = self.root / FROZEN_FILES[kind]
        payload = _serialize(obj).encode("utf-8")
        sha = hashlib.sha256(payload).hexdigest()
        if path.exists():
            if path.read_bytes() == payload:
                return path, sha
            raise ContractError(
                f"{FROZEN_FILES[kind]} already exists with different "
                "content — a freeze is never rewritten in place (T7); "
                "the redo doors are Gate-2 rejection and the addendum "
                "replan")
        _atomic_write_json(path, obj)
        return path, sha

    def read_frozen(self, kind: str) -> dict:
        """The verified read of a frozen artifact (P25 item 5, P0-2):
        existence first — a missing freeze is FileNotFoundError, so every
        caller's existing refusal code (`missing_frozen_plan`, …) still
        fires — then the vouching gate checkpoint must exist, carry a
        `frozen_sha256`, and match the bytes on disk. A freeze nobody
        vouched for (a crash after the freeze, before the checkpoint) or
        one modified after the gate is refused, never read as authority."""
        name = FROZEN_FILES[kind]
        path = self.root / name
        if not path.exists():
            raise FileNotFoundError(path)
        stage = FROZEN_GATES[kind]
        recorded = None
        if stage in self.completed_stages():
            recorded = self.checkpoint_payload(stage).get("frozen_sha256")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if recorded is None:
            raise ContractError(
                f"{name} has no {stage} checkpoint vouching for it "
                "(frozen_sha256 absent) — a freeze without its gate record "
                "is not an authority; resubmit the gate decision")
        if recorded != actual:
            raise ContractError(
                f"{name} fails verification against the {stage} checkpoint "
                f"(recorded {recorded[:12]}…, on disk {actual[:12]}…) — the "
                "frozen copy was modified after the gate")
        return json.loads(path.read_text(encoding="utf-8"))

    def archive_frozen(self, kind: str, dest: str) -> str:
        """The one sanctioned move of a frozen file: intact, never
        rewritten, never over an existing archive. Returns the sha256 of
        the moved bytes so the caller's record can attest the archive."""
        src = self.root / FROZEN_FILES[kind]
        if not src.exists():
            raise FileNotFoundError(src)
        target = self._under_root(dest)
        if target.exists():
            raise ContractError(
                f"archive target {dest!r} already exists — an archive is "
                "never overwritten")
        sha = hashlib.sha256(src.read_bytes()).hexdigest()
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(src, target)
        return sha

    def file_sha256(self, name: str) -> str | None:
        """The ONE digest of a workspace file's bytes (P25 C0): every hash
        binding — draft→frozen plan, annotated→draft, checkpoint→freeze —
        is computed here and nowhere else. A missing file is None, never
        an exception: a predicate that compares against None simply fails
        to match, which is the honest answer for a file that is gone."""
        path = self.root / name
        if not path.exists():
            return None
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def write_json(self, name: str, obj: dict) -> Path:
        """Atomic JSON write for non-artifact workspace files. Callers
        validate content; this seam only guarantees atomicity and the
        deterministic serializer. (slots.json graduated to a registered
        contract kind at P9/E4 — B25's non-addition closed by B26's
        write-back dependency.) Frozen names are refused here too."""
        self._refuse_frozen_name(name)
        path = self._under_root(name)
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
        """The one destructive workspace operation, reserved for redo
        doors: Gate-2 rejection and the addendum replan clear the planning
        stages, Gate-0 rejection clears intake, the review loop clears its
        round (the cleared stages must genuinely rerun). Missing
        checkpoints are fine (idempotent)."""
        (self.root / "checkpoints" / f"{stage}.json").unlink(missing_ok=True)

    # -- runs --------------------------------------------------------------

    def new_run_id(self) -> str:
        return mint_run_id(self.root / "runs")

    def latest_run_id(self) -> str | None:
        return latest_run_id_in(self.root / "runs")
