"""Assistant sessions (P14/B63): session = run.

Home is <workspace>/support/assistant/ — a directory the pursuit walker
structurally cannot see (is_pursuit_dir wants brief.json or inbox/), so
assistant spend can never pool into pursuit cost aggregates (the D21
unmixability property, inherited by location). The RunLogger is
resume-safe, so every HTTP turn reopens the same gapless run; run_end
is emitted only on an explicit close — an open session is honestly an
open run.

Spend is DERIVED, never stored: spent-so-far is the sum of the session
log's own agent_call lines, the same lines the audit trail is made of."""

import json
import re
import secrets
from pathlib import Path

from engine.contracts import append_fsync

from engine.runlog.writer import RunLogger

SESSION_CEILING_USD = 5.0
MAX_MESSAGE_CHARS = 4000
_SESSION_RX = re.compile(r"^sas_[a-z0-9]{8}$")


class UnknownSession(KeyError):
    pass


class AssistantSession:
    def __init__(self, workspace: Path, session_id: str, *,
                 resume: bool = False):
        if not _SESSION_RX.match(session_id):
            raise UnknownSession(session_id)  # also the traversal guard
        self.workspace = Path(workspace)
        self.session_id = session_id
        root = self.workspace / "support" / "assistant"
        self.run_dir = root / "runs" / session_id
        self.logger = RunLogger(root, session_id, "assistant", resume=resume)
        self.transcript_path = self.run_dir / "transcript.jsonl"

    # -- lifecycle ---------------------------------------------------------

    @classmethod
    def mint(cls, workspace: Path, *, mode: str, engine_version: str,
             config: dict, kb_snapshot: str) -> "AssistantSession":
        session = cls(workspace, "sas_" + secrets.token_hex(4))
        session.logger.run_start(mode=mode, engine_version=engine_version,
                                 config=config, kb_snapshot=kb_snapshot)
        return session

    @classmethod
    def load(cls, workspace: Path, session_id: str) -> "AssistantSession":
        if not _SESSION_RX.match(session_id or ""):
            raise UnknownSession(session_id)
        run_file = (Path(workspace) / "support" / "assistant" / "runs"
                    / session_id / "run.jsonl")
        if not run_file.exists():
            raise UnknownSession(session_id)
        return cls(workspace, session_id, resume=True)

    # -- transcript --------------------------------------------------------

    def append(self, record: dict) -> None:
        append_fsync(self.transcript_path,
                     json.dumps(record, sort_keys=True,
                                separators=(",", ":")))  # P0-6

    def transcript(self) -> list[dict]:
        if not self.transcript_path.exists():
            return []
        return [json.loads(line) for line in
                self.transcript_path.read_text(
                    encoding="utf-8").splitlines()]

    def earned(self) -> tuple[set, set, set]:
        """Rebuild the citation vocabulary from the persisted transcript:
        (docs read, cards opened, proposals opened) across the session."""
        docs, cards, proposals = set(), set(), set()
        for record in self.transcript():
            docs.update(record.get("earned_docs", ()))
            cards.update(record.get("earned_cards", ()))
            proposals.update(record.get("earned_proposals", ()))
        return docs, cards, proposals

    # -- spend -------------------------------------------------------------

    def spent_usd(self) -> float:
        spent = 0.0
        if self.logger.path.exists():
            for line in self.logger.path.read_text(
                    encoding="utf-8").splitlines():
                record = json.loads(line)
                if record.get("record_type") == "agent_call":
                    spent += record.get("cost_usd", 0.0)
        return round(spent, 6)
