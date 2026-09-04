"""The proposal store — S4's "proposals with a diff, never silent
commits" made structural.

Every door that would change knowledge-base CONTENT writes one of these
and stops. A steward decides. The only path that touches a card without
a proposal is the derived-signal write (edit_survival), which changes no
content and is recomputed from the record rather than authored.

This is the anti-poisoning control (T3): content that can enter the
corpus without a human seeing it is content an attacker, or a confused
agent, can plant. The diff is what makes the human's look meaningful —
v1's lesson was that a review of descriptions rather than diffs becomes
rubber-stamping.
"""

import hashlib
import json
import re
from pathlib import Path

from engine.contracts import (ContractError, path_lock, read_json,
                              validate, write_json_atomic)


def proposal_id(source: dict, kind: str, kb_id: str | None,
                diff: dict) -> str:
    """Deterministic from content, so proposing the same change twice
    yields the same id rather than a growing pile of duplicates a
    steward has to recognise as identical."""
    payload = json.dumps(
        {"source": source, "kind": kind, "kb_id": kb_id, "diff": diff},
        sort_keys=True)
    return "prop_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


# The schema's own pattern (kb-proposal.schema.json) — P1-39 tightened
# the door to it; the P26b-1 shape admitted ids the record refused.
PROPOSAL_ID = re.compile(r"prop_[a-z0-9]{4,32}")


class IdShapeError(ValueError):
    """P2-23 (P26b-1, B112): an id that is not the shape `proposal_id`
    mints — refused before it can name a path. (The KB store has its
    twin in engine/kb/identity.py; the graph has no flywheel→kb edge.)"""


def require_proposal_id(value) -> str:
    if not isinstance(value, str) or PROPOSAL_ID.fullmatch(value) is None:
        raise IdShapeError(
            f"not a proposal_id: {value!r} (expected prop_ + 4-32 of [a-z0-9])")
    return value


def _proposal_record(path: Path) -> dict:
    record = read_json(path)  # M-30: a bad file refuses naming itself
    if "status" not in record or "proposal_id" not in record:
        raise ContractError(
            f"{path}: not a proposal record (no status/proposal_id) — the "
            "record is evidence, stop and see the recovery runbook")
    return record


class ProposalStateError(ValueError):
    """P1-39 (P26b-2): a decision is made ONCE. A proposal that is no
    longer `proposed` refuses a second decision by name — the reject
    door used to overwrite an accepted proposal's decided block while
    the curation log still recorded the merge."""


DECIDABLE = ("proposed",)


class ProposalStore:
    """One JSON file per proposal under <kb_root>/proposals/."""

    def __init__(self, kb_root: Path):
        self.kb_root = Path(kb_root)  # the lock key curation.py shares
        self.root = self.kb_root / "proposals"

    def _path(self, pid: str) -> Path:
        # P2-23: every read and write door names its path through here.
        return self.root / f"{require_proposal_id(pid)}.json"

    def open(self, *, source: dict, target: str, kind: str, at: str,
             kb_id: str | None = None, diff: dict | None = None,
             note: str = "") -> dict:
        proposal = {
            "proposal_id": proposal_id(source, kind, kb_id, diff or {}),
            "created": at,
            "status": "proposed",
            "source": source,
            "target": target,
            "kind": kind,
        }
        if kb_id:
            proposal["kb_id"] = kb_id
        if diff:
            proposal["diff"] = diff
        if note:
            proposal["note"] = note
        validate("kb_proposal", proposal)
        path = self._path(proposal["proposal_id"])
        # Re-proposing an identical change is a no-op, not a duplicate:
        # the flywheel runs repeatedly over a growing record and would
        # otherwise re-raise every lesson it has ever drawn. The
        # exists-check and the write are one step under the root's lock
        # (P1-40).
        with path_lock(self.kb_root):
            self.root.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                write_json_atomic(path, proposal, indent=1)  # P0-6
            return json.loads(path.read_text(encoding="utf-8"))

    def read(self, pid: str) -> dict:
        path = self._path(pid)
        if not path.exists():
            raise FileNotFoundError(path)
        return _proposal_record(path)

    def list(self, *, status: str | None = None) -> list[dict]:
        """Every proposal, or those in one status. A file that is not a
        proposal record refuses by name (M-30): the inbox used to 500 on
        it and hide every other pending decision."""
        if not self.root.is_dir():
            return []
        out = [_proposal_record(p) for p in sorted(self.root.glob("prop_*.json"))]
        return [p for p in out if status is None or p["status"] == status]

    def decide(self, pid: str, *, decision: str, by: str, at: str,
               note: str = "") -> dict:
        """Record a steward's disposition ON the proposal, so what was
        decided and the decision never drift apart. Nothing is deleted —
        a rejected proposal is evidence about what the flywheel wanted."""
        with path_lock(self.kb_root):  # P1-40: the RMW is one step
            proposal = self.read(pid)
            if proposal["status"] not in DECIDABLE:
                raise ProposalStateError(
                    f"{pid} is already {proposal['status']} — a decision "
                    "is made once")
            proposal["status"] = decision
            proposal["decided"] = {"by": by, "at": at, "decision": decision}
            if note:
                proposal["decided"]["note"] = note
            validate("kb_proposal", proposal)
            write_json_atomic(self._path(pid), proposal, indent=1)  # P0-6 RMW
            return proposal
