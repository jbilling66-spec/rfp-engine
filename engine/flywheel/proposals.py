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
from pathlib import Path

from engine.contracts import validate, write_json_atomic


def proposal_id(source: dict, kind: str, kb_id: str | None,
                diff: dict) -> str:
    """Deterministic from content, so proposing the same change twice
    yields the same id rather than a growing pile of duplicates a
    steward has to recognise as identical."""
    payload = json.dumps(
        {"source": source, "kind": kind, "kb_id": kb_id, "diff": diff},
        sort_keys=True)
    return "prop_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


class ProposalStore:
    """One JSON file per proposal under <kb_root>/proposals/."""

    def __init__(self, kb_root: Path):
        self.root = Path(kb_root) / "proposals"

    def _path(self, pid: str) -> Path:
        return self.root / f"{pid}.json"

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
        self.root.mkdir(parents=True, exist_ok=True)
        path = self._path(proposal["proposal_id"])
        # Re-proposing an identical change is a no-op, not a duplicate:
        # the flywheel runs repeatedly over a growing record and would
        # otherwise re-raise every lesson it has ever drawn.
        if not path.exists():
            write_json_atomic(path, proposal, indent=1)  # P0-6
        return json.loads(path.read_text(encoding="utf-8"))

    def read(self, pid: str) -> dict:
        return json.loads(self._path(pid).read_text(encoding="utf-8"))

    def list(self, *, status: str | None = None) -> list[dict]:
        if not self.root.is_dir():
            return []
        out = [json.loads(p.read_text(encoding="utf-8"))
               for p in sorted(self.root.glob("prop_*.json"))]
        return [p for p in out if status is None or p["status"] == status]

    def decide(self, pid: str, *, decision: str, by: str, at: str,
               note: str = "") -> dict:
        """Record a steward's disposition ON the proposal, so what was
        decided and the decision never drift apart. Nothing is deleted —
        a rejected proposal is evidence about what the flywheel wanted."""
        proposal = self.read(pid)
        proposal["status"] = decision
        proposal["decided"] = {"by": by, "at": at, "decision": decision}
        if note:
            proposal["decided"]["note"] = note
        validate("kb_proposal", proposal)
        write_json_atomic(self._path(pid), proposal, indent=1)  # P0-6 RMW
        return proposal
