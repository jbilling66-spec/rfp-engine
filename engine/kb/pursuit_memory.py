"""Tier-2 memory: the pursuit's own retrievable context (P17/C4, B69§2).

The supplemental material B66§5 names — a prior proposal to this buyer,
the SME's technical notes, an incumbent contract — must not become
permanent KB cards (pursuit-specific context would pollute the firm
corpus and survive the pursuit), so it lands in a second KBStore at
<pursuit>/memory: retrievable beside the firm KB through the Lanes
bundle, retained with the pursuit (B69§1 — the owner's retention call),
purged with it, never entering the firm corpus.

This door is deliberately LIGHTER than firm ingest: deterministic
chunking, zero model calls (the zero-spend law), no anonymization pass —
the material never leaves the pursuit it belongs to. Cards mint pkb_
ids (the lane rides the id), record authored_by on the RESTRICTED
provenance (the C2 field: the pursuit lane accepts firm, buyer, and
third-party sources because nothing here ever grounds a Tier-1 claim),
and are structurally barred from the fact catalog: this writer only
ever mints layer="corpus", and validation receives the firm store alone
(the C4 firewall test proves both belts).

PDFs and other non-text formats refuse LOUDLY with a recorded error
(closer: A1/extraction — the F4 precedent); a refusal is surfaced,
never a silent skip.
"""

import hashlib
from pathlib import Path

from engine.kb.lanes import PURSUIT_PREFIX
from engine.kb.store import KBStore, snapshot_id

MEMORY_DIR = "memory"
_TEXT_SUFFIXES = (".md", ".txt")
_SUMMARY_CHARS = 200


def memory_root(pursuit_root: Path) -> Path:
    return Path(pursuit_root) / MEMORY_DIR


def memory_store(pursuit_root: Path) -> KBStore:
    return KBStore(memory_root(pursuit_root))


def memory_snapshot(pursuit_root: Path) -> str | None:
    """Snapshot of the pursuit lane, None when it holds nothing — so the
    run_start field appears only when set and pre-P17 headers stay
    byte-identical (the C1 rule)."""
    root = memory_root(pursuit_root)
    if not (root / "cards").is_dir():
        return None
    snap = snapshot_id(root)
    return None if snap == "kb@empty" else snap


def _chunks_from_text(text: str, fallback_title: str) -> list[tuple[str, str]]:
    """Deterministic heading-split: each markdown heading opens a chunk
    titled by it; leading unheaded text (or a heading-free document)
    chunks under the filename."""
    chunks: list[tuple[str, list[str]]] = []
    title = fallback_title
    lines: list[str] = []
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            if lines and any(l.strip() for l in lines):
                chunks.append((title, lines))
            title = line.lstrip().lstrip("#").strip() or fallback_title
            lines = []
        else:
            lines.append(line)
    if lines and any(l.strip() for l in lines):
        chunks.append((title, lines))
    return [(t, "\n".join(ls).strip()) for t, ls in chunks]


def _chunks_from_docx(path: Path, fallback_title: str) -> list[tuple[str, str]]:
    from docx import Document

    chunks: list[tuple[str, list[str]]] = []
    title = fallback_title
    lines: list[str] = []
    for para in Document(str(path)).paragraphs:
        style = para.style.name if para.style else ""
        if style.startswith("Heading"):
            if lines and any(l.strip() for l in lines):
                chunks.append((title, lines))
            title = para.text.strip() or fallback_title
            lines = []
        elif para.text.strip():
            lines.append(para.text)
    if lines and any(l.strip() for l in lines):
        chunks.append((title, lines))
    return [(t, "\n".join(ls).strip()) for t, ls in chunks]


def _summary(body: str) -> str:
    flat = " ".join(body.split())
    return flat[:_SUMMARY_CHARS]


def deposit_supplemental(pursuit, name: str, *, authored_by: str,
                         log, stage: str, agent: str = "pursuit_memory",
                         ) -> list[str]:
    """Chunk one inbox file into the pursuit's memory lane. Returns the
    minted pkb_ ids (already-present chunks skip — content-anchored ids
    make the deposit idempotent). Unsupported formats emit a recorded
    error and return [] — refused, never dropped."""
    source = Path(pursuit.root) / "inbox" / name
    fallback = source.stem.replace("-", " ").replace("_", " ").strip()
    suffix = source.suffix.lower()
    if suffix in _TEXT_SUFFIXES:
        chunks = _chunks_from_text(
            source.read_text(encoding="utf-8"), fallback)
    elif suffix == ".docx":
        chunks = _chunks_from_docx(source, fallback)
    else:
        log.emit("error", stage=stage, error={
            "code": "memory_deposit_unsupported",
            "message": f"{name}: {suffix or 'no extension'} is not a "
                       "memory-depositable format on the offline path — "
                       "pdf and binary supplements join at A1/extraction",
            "recoverable": True,
            "action_taken": "surfaced_to_human",
        })
        return []

    store = memory_store(pursuit.root)
    minted: list[str] = []
    for title, body in chunks:
        digest = hashlib.sha256(f"{name}\n{body}".encode()).hexdigest()[:10]
        kb_id = f"{PURSUIT_PREFIX}{digest}"
        if store.card_exists(kb_id):
            continue
        card = {
            "kb_id": kb_id,
            "layer": "corpus",  # NEVER fact_sheet — this writer's law
            "title": title,
            "summary": _summary(body),
        }
        store.write_card(
            card, body,
            {"source_pursuit": pursuit.pursuit_id,
             "authored_by": authored_by},
            {},
        )
        minted.append(kb_id)
    if minted:
        log.emit("artifact", stage=stage, artifact={
            "kind": "pursuit_memory",
            "path": f"{MEMORY_DIR}/cards ({name})",
            "sha256": snapshot_id(memory_root(pursuit.root)).split("@")[1],
        })
    return minted
