"""Content-anchored card identity (C6, WP13 R6).

The id is a hash of the chunk's own normalized text — nothing else. The
pre-P13 scheme hashed the WHOLE source document plus an ordinal, so one
changed byte anywhere rotated every card id from that document and
write_card_signals silently dropped the orphaned edit_survival scores.
Content-anchoring inverts that: an id moves only when its own content
moves, and then reconciliation (C9) carries the history across under
the ORIGINAL id.

Normalization is deliberately coarse (whitespace-collapse + casefold):
a reflow, a wrap-width change, or a case-styling pass is the same
content and must keep the same id. Anything semantic is drift, and
drift is reconciliation's job, not identity's.

Two chunks with identical normalized text mint the same id — that is
the point, not a collision: the same boilerplate in eleven responses is
ONE card with eleven sources folded into its restricted record (dedup
unit = card, B59/D4).

structural_key (heading path + element ordinal) is the match TIEBREAK
for reconciliation, never identity itself (KB10: a heading path is one
buyer's demanded outline).
"""

import hashlib
import re

_WHITESPACE = re.compile(r"\s+")


def normalize(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip().casefold()


def content_hash(text: str) -> str:
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()


# The three lanes' prefixes (engine/kb/lanes.py: firm `kb_`, pursuit
# `pkb_`, org `okb_`) — listed here rather than imported, so identity
# stays the leaf module; tests/kb/test_id_shape.py pins the agreement.
KB_ID = re.compile(r"(?:kb|pkb|okb)_[a-z0-9][a-z0-9_-]{0,40}")


class IdShapeError(ValueError):
    """P2-23 (P26b-1, B112): an id that is not the shape this engine
    mints — refused at the store boundary, BEFORE it can name a path."""


def require_kb_id(value) -> str:
    """Prefixed and path-safe — the pursuit-id precedent: `kb_` then
    lowercase alphanumerics, `_` or `-`, at most 41 chars. `kb_id_for` mints
    the hex subset; fixtures and seeds use readable ids of the same shape.
    No `/`, `.`, upper case, whitespace or non-string can name a path."""
    if not isinstance(value, str) or KB_ID.fullmatch(value) is None:
        raise IdShapeError(
            f"not a kb_id: {value!r} (expected kb_/pkb_/okb_ + [a-z0-9_-], path-safe)")
    return value


def kb_id_for(text: str) -> str:
    return "kb_" + content_hash(text)[:10]


def structural_key(doc_path: list[str], ordinal: int) -> str:
    """'6.0 Accelerators/6.0.2 Data Migration#3' — the chunk's place in
    the document, for drift tiebreaks in reconciliation."""
    return "/".join(doc_path) + f"#{ordinal}"


def identity_block(text: str, doc_path: list[str], ordinal: int,
                   source_hash: str) -> dict:
    """The card's identity field (kb-card schema): everything the C9
    matcher needs to recognize this card in a future re-ingestion.
    matched_from and drift are reconciliation outputs and land there."""
    return {
        "content_hash": content_hash(text),
        "structural_key": structural_key(doc_path, ordinal),
        "source_hash": source_hash,
    }
