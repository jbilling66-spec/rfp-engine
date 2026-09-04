"""KB card store: YAML-frontmatter + markdown files, one writer, split write.

Cards are the ONLY retrievable text (K3). render_card/parse_card are the one
render/parse pair in the codebase — v1 nearly corrupted a pack because two
writers disagreed on frontmatter style, so a second writer is a bug by
definition. The round-trip contract parse(render(card, body)) == (card, body)
is asserted in tests over every card the suite creates.

write_card validates the JOINED card+provenance object against the kb-card
contract, then splits: frontmatter + body go to cards/<kb_id>.md; provenance
and the identifier map go to the RestrictedStore (S8) and never into a card
file. Retrieval reads cards/ only — there is no code path from search to
provenance (B14).
"""

import hashlib
from pathlib import Path

import yaml

from engine.contracts import validate, write_text_atomic
from engine.kb.identity import require_kb_id
from engine.kb.provenance import RestrictedStore


_atomic_write_text = write_text_atomic  # P0-6: one primitive, one home


def render_card(card: dict, body: str) -> str:
    """The one card writer. Deterministic: sorted keys, block style, no wrap."""
    if "provenance" in card:
        raise ValueError(
            "provenance is RESTRICTED (S8) and never enters a card file; "
            "it belongs to the RestrictedStore"
        )
    front = yaml.safe_dump(
        card, sort_keys=True, default_flow_style=False, allow_unicode=True,
        width=10**6,
    )
    return f"---\n{front}---\n{body.strip()}\n"


def parse_card(text: str) -> tuple[dict, str]:
    """The one card parser. Splits at the FIRST closing fence only, so a
    markdown rule inside the body cannot truncate it."""
    if not text.startswith("---\n"):
        raise ValueError("card file must start with a '---' frontmatter fence")
    front, sep, body = text[len("---\n"):].partition("\n---\n")
    if not sep:
        raise ValueError("card file has no closing '---' frontmatter fence")
    return yaml.safe_load(front), body.strip()


def snapshot_id(root: Path) -> str:
    """Content digest over cards/ — the retrievable text is what makes two
    runs comparable (O4). Restricted content cannot influence a run and is
    deliberately outside the digest."""
    cards_dir = Path(root) / "cards"
    files = sorted(cards_dir.glob("*.md")) if cards_dir.exists() else []
    if not files:
        return "kb@empty"
    h = hashlib.sha256()
    for path in files:
        h.update(path.name.encode())
        h.update(hashlib.sha256(path.read_bytes()).digest())
    return f"kb@{h.hexdigest()[:12]}"


class KBStore:
    def __init__(self, root: Path, restricted: RestrictedStore | None = None):
        self.root = Path(root)
        self.cards_dir = self.root / "cards"
        self.cards_dir.mkdir(parents=True, exist_ok=True)
        self.restricted = restricted or RestrictedStore(self.root)

    def _card_path(self, kb_id: str) -> Path:
        # P2-23: every read and write door names its path through here.
        return self.cards_dir / f"{require_kb_id(kb_id)}.md"

    def write_card(
        self, card: dict, body: str, provenance: dict, identifiers: dict[str, str]
    ) -> Path:
        """Validate the joined object, then split-write: card file public,
        provenance + identifier map restricted. identifiers maps each original
        string to the placeholder type that replaced it — the index the
        anonymization scan and the purge sweep run against."""
        validate("kb_card", {**card, "provenance": provenance})
        path = self._card_path(card["kb_id"])
        _atomic_write_text(path, render_card(card, body))
        self.restricted.write(card["kb_id"], provenance, identifiers)
        return path

    def read_card(self, kb_id: str) -> tuple[dict, str]:
        return parse_card(self._card_path(kb_id).read_text(encoding="utf-8"))

    def update_card_front(self, kb_id: str, **fields) -> Path:
        """Rewrite frontmatter fields, body untouched (P10 flywheel).

        Deliberately narrow: this is the door the flywheel uses to write
        a derived SIGNAL (edit_survival) back onto a card, not a general
        edit path — content changes go through the proposal lane so a
        human sees a diff (S4). Validation runs on the card alone;
        provenance is not read, not rewritten, and not required, so a
        signal write can never disturb the restricted split."""
        card, body = self.read_card(kb_id)
        updated = {**card, **fields}
        validate("kb_card", updated)
        path = self._card_path(kb_id)
        _atomic_write_text(path, render_card(updated, body))
        return path

    def append_lesson(self, kb_id: str, entry: dict) -> Path:
        """P26c (P1-43): the flywheel's other write onto a card — an
        ACCEPTED lesson (a reviewer's prose about this card, carried by
        the steward's merge) appended to lessons[], body untouched,
        validated whole through the same narrow door as edit_survival.
        Idempotent on proposal_id: the same accepted proposal cannot land
        twice."""
        card, _body = self.read_card(kb_id)
        lessons = list(card.get("lessons") or [])
        if any(l.get("proposal_id") == entry.get("proposal_id")
               for l in lessons):
            return self._card_path(kb_id)
        return self.update_card_front(kb_id, lessons=[*lessons, entry])

    def rewrite_card(self, card: dict, body: str) -> Path:
        """Replace a card's content under its EXISTING id — the drifted-
        match write of re-ingest reconciliation (P13/C9, R6: the id never
        changes; version increments). Deliberately narrow like
        update_card_front: the restricted record is not rewritten (the
        caller appends the new source), so a reconciliation can never
        disturb the provenance split. Refuses a card that does not exist
        — minting goes through write_card."""
        kb_id = card["kb_id"]
        if not self.card_exists(kb_id):
            raise ValueError(f"rewrite_card: {kb_id} does not exist")
        validate("kb_card", card)
        path = self._card_path(kb_id)
        _atomic_write_text(path, render_card(card, body))
        return path

    def card_exists(self, kb_id: str) -> bool:
        return self._card_path(kb_id).exists()

    def list_cards(self) -> list[dict]:
        return [
            parse_card(p.read_text(encoding="utf-8"))[0]
            for p in sorted(self.cards_dir.glob("*.md"))
        ]

    def delete_card(self, kb_id: str) -> None:
        """Purge (D1) and dedup-merge replacement are the only callers.
        Cards are otherwise append/replace."""
        self._card_path(kb_id).unlink()

    def snapshot(self) -> str:
        return snapshot_id(self.root)
