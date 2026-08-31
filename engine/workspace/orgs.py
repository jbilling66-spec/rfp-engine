"""Tier-3 memory: per-organization observations (P17/C6, B69§2).

"They like this specific thing" — firm-authored observations about a
buyer that outlive any one pursuit. Sited as a WORKSPACE sibling
(<workspace>/orgs/<org_id>/, beside kb/ and the reserved advisor lane):
physically outside every pursuit tree, so a pursuit purge cannot take
it and an org purge takes exactly it.

THE HARD BOUNDARY (B69§3): never retained buyer text. Enforced
structurally, not by policy — this module's write_org_note is the org
store's ONLY writer, it accepts typed operator text and stamps
content_origin=human_authored + authored_by=firm; no ingest path
accepts an org root (proven by the named test). Cards mint okb_ ids so
every trace line self-describes the lane.

Identity is HUMAN-LINKED, never inferred (the document-role precedent):
an opaque org_NNNN id with known_as aliases in org.json — the buyer's
name lives only in file CONTENT, never in ids, paths, or git history
(the neutral-names standing instruction; synthetic names in tests).
Linking happens at gate_0 (approve_gate0's org step) and stamps
buyer.org_id on the brief pre-freeze.

Org memory feeds STRATEGY surfaces only (B75§1c, the owner's call): the lane
joins research retrieval, never the mapper's grounding verdicts, and is
never cited in drafted prose.
"""

import hashlib
import json
from pathlib import Path

from engine.contracts import ContractError
from engine.kb.lanes import ORG_PREFIX
from engine.kb.store import KBStore, snapshot_id

ORGS_DIR = "orgs"


def orgs_root(workspace: Path) -> Path:
    return Path(workspace) / ORGS_DIR


def _org_file(workspace: Path, org_id: str) -> Path:
    return orgs_root(workspace) / org_id / "org.json"


def read_org(workspace: Path, org_id: str) -> dict:
    path = _org_file(workspace, org_id)
    if not path.exists():
        raise ContractError(f"unknown org {org_id!r} — link an existing "
                            "org or create one at gate_0")
    return json.loads(path.read_text(encoding="utf-8"))


def list_orgs(workspace: Path) -> list[dict]:
    root = orgs_root(workspace)
    if not root.is_dir():
        return []
    return [json.loads(p.read_text(encoding="utf-8"))
            for p in sorted(root.glob("org_*/org.json"))]


def _write_org(workspace: Path, org: dict) -> dict:
    path = _org_file(workspace, org["org_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(org, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")
    return org


def create_org(workspace: Path, name: str, *, created_by: str,
               at: str) -> dict:
    """Mint the next opaque org id and register the display name as its
    first alias. The name lives in this file's CONTENT only."""
    if not (name or "").strip():
        raise ContractError("an org needs a display name to alias")
    existing = {o["org_id"] for o in list_orgs(workspace)}
    n = 1
    while f"org_{n:04d}" in existing:
        n += 1
    return _write_org(workspace, {
        "org_id": f"org_{n:04d}", "known_as": [name.strip()],
        "created_by": created_by, "created_at": at,
    })


def link_alias(workspace: Path, org_id: str, name: str) -> dict:
    """A pursuit linking under a new display name records the alias —
    how 'County of X' and 'X County' stay one organization."""
    org = read_org(workspace, org_id)
    clean = (name or "").strip()
    if clean and clean not in org["known_as"]:
        org["known_as"].append(clean)
        _write_org(workspace, org)
    return org


def org_memory_root(workspace: Path, org_id: str) -> Path:
    return orgs_root(workspace) / org_id / "memory"


def org_store(workspace: Path, org_id: str) -> KBStore:
    read_org(workspace, org_id)  # loudly refuse an unregistered org
    return KBStore(org_memory_root(workspace, org_id))


def org_snapshot(workspace: Path, org_id: str) -> str | None:
    root = org_memory_root(workspace, org_id)
    if not (root / "cards").is_dir():
        return None
    snap = snapshot_id(root)
    return None if snap == "kb@empty" else snap


def write_org_note(workspace: Path, org_id: str, *, operator: str,
                   at: str, title: str, body: str) -> str:
    """The org store's ONLY writer: a typed, firm-authored observation.
    content_origin=human_authored and authored_by=firm are stamped by
    this door, not trusted from the caller — retained buyer text has no
    path in (B69§3)."""
    if not (title or "").strip() or not (body or "").strip():
        raise ContractError("an org note needs a title and a body")
    if not (operator or "").strip():
        raise ContractError("an org note records who observed it")
    store = org_store(workspace, org_id)
    digest = hashlib.sha256(f"{title}\n{body}".encode()).hexdigest()[:10]
    kb_id = f"{ORG_PREFIX}{digest}"
    if store.card_exists(kb_id):
        return kb_id
    store.write_card(
        {"kb_id": kb_id, "layer": "corpus",
         "title": title.strip(),
         "summary": " ".join(body.split())[:200],
         "content_origin": "human_authored"},
        body.strip(),
        {"ingested_by": operator, "date": at[:10], "authored_by": "firm"},
        {},
    )
    return kb_id
