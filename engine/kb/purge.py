"""Purge on request (D1): remove a source client's material and everything
derived from it, then PROVE the removal with a sweep.

Closure: every card whose restricted record names the client in any
contributing source (merged cards count — that is why merge folds sources
in), expanded transitively over derived_from links. legal_hold cards are
subtracted and reported, never silently skipped (D2: hold overrides
retention automation, and a silent skip would read as a completed purge).

The sweep is belt and braces: the purged records' identifier strings are
captured BEFORE deletion (afterwards there is nothing to sweep against),
then every remaining retrievable text is scanned for them with the same
scanner the ingestion gate trusts. A clean report — not the deletion loop
finishing — is the evidence the client commitment was honored, and the
verdict lands in the access log.
"""

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from engine.kb.anonymize import scan
from engine.kb.canonical import model_path
from engine.kb.store import KBStore, _atomic_write_text


@dataclass
class PurgeReport:
    client: str
    purged: list[str] = field(default_factory=list)
    held: list[str] = field(default_factory=list)  # legal_hold survivors (D2)
    swept_clean: bool = False
    sweep_findings: list = field(default_factory=list)
    accounting: dict | None = None  # C16: the full five-stage accounting
    accounting_path: str | None = None


@dataclass
class PurgeAccounting:
    """R8's mandate made literal (C16): the cascade produces an
    accounting of everything it touched at every stage, and completing
    without one is a FAILURE — purge_client raises if any closure
    member ends the run unaccounted. Persisted in the restricted store
    (it names the client). L2 and L4 get statements rather than lists:
    chunks live inside the L1 model files, and the catalog is computed,
    never persisted (KB8 disposition, B59)."""
    client: str
    l0_sources: list[str] = field(default_factory=list)
    l1_models: list[str] = field(default_factory=list)
    l2_statement: str = ("chunks live inside the L1 model files and are "
                        "deleted with them")
    l3_cards: list[str] = field(default_factory=list)
    l4_statement: str = ("computed catalog — no persisted state to delete; "
                         "the next list_cards() reflects the purge")
    drafts: list[dict] = field(default_factory=list)
    held_cards: list[str] = field(default_factory=list)
    held_models: list[str] = field(default_factory=list)
    held_sources: list[str] = field(default_factory=list)
    sweep_clean: bool = False


def _closure(store: KBStore, client: str, *, actor: str) -> tuple[set[str], list[str]]:
    """Cards naming the client in any source, expanded over derived_from.
    Also returns every identifier string those records carried."""
    restricted = store.restricted
    seeds: set[str] = set()
    identifiers: set[str] = set()
    derived_edges: dict[str, set[str]] = {}
    for path in sorted(restricted.prov_dir.glob("*.json")):
        record = restricted.read(path.stem, actor=actor, purpose="purge")
        derived_edges[path.stem] = set(record.get("derived_from", []))
        if any(s.get("source_client") == client for s in record["sources"]):
            seeds.add(path.stem)
            identifiers.update(record["identifiers"])

    closure = set(seeds)
    changed = True
    while changed:
        changed = False
        for kb_id, parents in derived_edges.items():
            if kb_id not in closure and parents & closure:
                closure.add(kb_id)
                changed = True
    return closure, sorted(identifiers)


def post_purge_sweep(store: KBStore, purged_identifiers: list[str],
                     purged_kb_ids: list[str],
                     extra_stores: list[KBStore] | None = None) -> list:
    """Prove the purge: no purged identifier and no purged card remains
    retrievable — in ANY lane. P17/C7: `extra_stores` widens the scan to
    every other retrievable store (pursuit memory, org memory); default
    keeps the pre-P17 firm-only behavior byte-stable. The CLEAN verdict
    is only as wide as this scan, so a lane left out silently narrows
    the claim — pass them all."""
    from engine.flywheel.proposals import ProposalStore

    findings = []
    for lane_store in [store, *(extra_stores or [])]:
        texts = {}
        for card in lane_store.list_cards():
            _, body = lane_store.read_card(card["kb_id"])
            texts[card["kb_id"]] = " ".join([
                card.get("title", ""), card.get("summary", ""), body,
                " ".join(card.get("question_forms", [])),
                # P26c: a lesson is retrievable text on the card too
                " ".join(f"{l.get('before', '')} {l.get('after', '')} "
                         f"{l.get('note', '')}"
                         for l in card.get("lessons") or []),
            ])
        # P26c: proposals are steward-visible and the drafter reads the
        # accepted notes — a purged identifier surviving there is a
        # finding, the same as on a card
        for proposal in ProposalStore(lane_store.root).list():
            strings = [proposal.get("note", "")]
            for change in (proposal.get("diff") or {}).values():
                if isinstance(change, dict):
                    strings.extend(str(v) for v in change.values()
                                   if v is not None)
            texts[f"proposal:{proposal['proposal_id']}"] = " ".join(strings)
        findings += list(scan(texts, purged_identifiers))
        findings += [
            f"{kb_id}: purged card still exists"
            for kb_id in purged_kb_ids if lane_store.card_exists(kb_id)
        ]
    return findings


def _lane_stores(pursuits_root: Path | None) -> list[KBStore]:
    """Every OTHER retrievable store under the workspace: each pursuit's
    memory lane and each org's memory lane (P17/C7). Only stores that
    actually hold cards — constructing a KBStore mkdirs, so probe first."""
    stores: list[KBStore] = []
    if not pursuits_root or not Path(pursuits_root).is_dir():
        return stores
    root = Path(pursuits_root)
    for cards_dir in sorted(root.glob("*/memory/cards")):
        if any(cards_dir.glob("*.md")):
            stores.append(KBStore(cards_dir.parent))
    for cards_dir in sorted(root.glob("orgs/*/memory/cards")):
        if any(cards_dir.glob("*.md")):
            stores.append(KBStore(cards_dir.parent))
    return stores


def _sweep_drafts(pursuits_root: Path, purged: set[str],
                  accounting: PurgeAccounting) -> None:
    """Derived draft content (R8): any draft or annotated-draft artifact
    with a section citing a purged card is deleted whole and accounted —
    client-derived prose does not outlive its source cards. Blunt by
    decision (B59 close-out records it): a draft is regenerable; a
    surgical section excision would leave a schema-shaped artifact
    quietly missing content."""
    if not pursuits_root or not Path(pursuits_root).is_dir():
        return
    for pursuit_dir in sorted(Path(pursuits_root).iterdir()):
        if not pursuit_dir.is_dir():
            continue
        for sub in ("drafts", "revisions"):
            for artifact in sorted((pursuit_dir / sub).glob("*.json")):
                try:
                    payload = json.loads(
                        artifact.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                sections = payload.get("sections", [])
                hit = [s.get("section_id") for s in sections
                       if set(s.get("cards_cited") or ()) & purged]
                if hit:
                    artifact.unlink()
                    accounting.drafts.append({
                        "pursuit": pursuit_dir.name,
                        "artifact": f"{sub}/{artifact.name}",
                        "sections": hit,
                    })


def _accounting_path(store: KBStore, client: str) -> Path:
    purges_dir = store.restricted.root / "purges"
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", client).strip("_") or "client"
    n = len(list(purges_dir.glob(f"{slug}-*.json"))) + 1
    return purges_dir / f"{slug}-{n:03d}.json"


def purge_client(store: KBStore, client: str, *, actor: str,
                 pursuits_root: Path | None = None) -> PurgeReport:
    """The firm-KB purge runs as one critical section under the root's
    lock (P1-40): a steward's merge landing mid-purge would write a
    card the closure never saw."""
    from engine.contracts import path_lock
    with path_lock(store.root):
        return _purge_client_locked(store, client, actor=actor,
                                    pursuits_root=pursuits_root)


def _purge_client_locked(store: KBStore, client: str, *, actor: str,
                         pursuits_root: Path | None = None) -> PurgeReport:
    report = PurgeReport(client=client)
    accounting = PurgeAccounting(client=client)
    closure, purged_identifiers = _closure(store, client, actor=actor)

    # L3 (cards), collecting each card's L1 lineage as it goes. A held
    # card holds its parents: you cannot delete the model or source an
    # item of retained evidence derives from (D2 at every layer).
    purged_cds: set[str] = set()
    held_cds: set[str] = set()
    for kb_id in sorted(closure):
        card, _ = store.read_card(kb_id)
        cd = card.get("canonical_doc_id")
        if card.get("legal_hold"):
            report.held.append(kb_id)
            accounting.held_cards.append(kb_id)
            if cd:
                held_cds.add(cd)
            continue
        store.delete_card(kb_id)
        store.restricted.delete(kb_id, actor=actor)
        report.purged.append(kb_id)
        accounting.l3_cards.append(kb_id)
        if cd:
            purged_cds.add(cd)

    # L1 + L0: models/sources of purged cards, plus L0 artifacts whose
    # restricted meta names the client directly — the blocked-ingest
    # case, which minted no cards and has no provenance record.
    direct_cds = {
        cd for cd, meta in store.restricted.source_metas(
            actor=actor, purpose="purge").items()
        if meta.get("source_client") == client
    }
    for cd in sorted((purged_cds | direct_cds)):
        if cd in held_cds:
            accounting.held_models.append(cd)
            accounting.held_sources.append(cd)
            continue
        l1 = model_path(store.root, cd)
        if l1.exists():
            l1.unlink()
            accounting.l1_models.append(cd)
        if store.restricted.source_exists(cd, actor=actor, purpose="purge"):
            store.restricted.delete_source(cd)
            accounting.l0_sources.append(cd)

    # Derived draft content across pursuit workspaces.
    _sweep_drafts(pursuits_root, set(report.purged), accounting)

    # Completing without the accounting is a failure (R8) — literal:
    # every closure member must appear exactly once, purged or held.
    unaccounted = closure - set(accounting.l3_cards) - set(
        accounting.held_cards)
    if unaccounted:
        raise RuntimeError(
            f"purge of {client!r} left closure member(s) unaccounted: "
            f"{sorted(unaccounted)} — the accounting IS the deliverable")

    # The client's own name sweeps even if no record listed it verbatim.
    # P17/C7: the scan covers EVERY retrievable lane under the workspace
    # — a pursuit or org lane holding the client's tokens is a FINDING
    # surfaced to the human (who purges that lane with its own entry
    # point); purge_client never guesses which pursuits are the client's.
    sweep_targets = sorted(set(purged_identifiers) | {client})
    report.sweep_findings = post_purge_sweep(
        store, sweep_targets, report.purged,
        extra_stores=_lane_stores(pursuits_root))
    report.swept_clean = not report.sweep_findings
    accounting.sweep_clean = report.swept_clean

    path = _accounting_path(store, client)
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(
        path, json.dumps(asdict(accounting), indent=1, sort_keys=True) + "\n")
    report.accounting = asdict(accounting)
    report.accounting_path = str(path)

    store.restricted.log_sweep(actor=actor, client=client,
                               clean=report.swept_clean, name=path.name)
    return report


def strip_carried_forward(store: KBStore, pursuit_id: str) -> tuple[list, list]:
    """P26c — D1 at the carry-forward layer: what a pursuit taught the
    firm KB goes with the pursuit. Its proposals (routed at accept,
    opted in at a gap answer, or hand-filled at writeback — the human's
    own words about that pursuit) are removed, and every lesson those
    proposals landed on a card is stripped from lessons[]. Under the
    firm root's lock; returns (proposal_ids, [{kb_id, proposal_id}]) for
    the accounting, and the caller re-reads the filesystem (P1-13)."""
    from engine.contracts import path_lock
    from engine.flywheel.proposals import ProposalStore

    proposals = ProposalStore(store.root)
    removed: list[str] = []
    lessons: list[dict] = []
    with path_lock(store.root):
        for proposal in proposals.list():
            if (proposal.get("source") or {}).get("pursuit_id") == pursuit_id:
                proposals.remove(proposal["proposal_id"])
                removed.append(proposal["proposal_id"])
        for card in store.list_cards():
            mine = [l for l in card.get("lessons") or []
                    if l.get("pursuit_id") == pursuit_id]
            if not mine:
                continue
            kept = [l for l in card["lessons"] if l not in mine]
            store.update_card_front(card["kb_id"], lessons=kept)
            lessons.extend({"kb_id": card["kb_id"],
                            "proposal_id": l["proposal_id"]} for l in mine)
    return sorted(removed), lessons


def _carried_forward_survivors(store: KBStore, pursuit_id: str) -> list[str]:
    from engine.flywheel.proposals import ProposalStore
    left = [p["proposal_id"] for p in ProposalStore(store.root).list()
            if (p.get("source") or {}).get("pursuit_id") == pursuit_id]
    left += [f"{c['kb_id']}:lesson" for c in store.list_cards()
             if any(l.get("pursuit_id") == pursuit_id
                    for l in c.get("lessons") or [])]
    return left


def _write_lane_accounting(dir_path: Path, name_prefix: str,
                           accounting: dict) -> Path:
    dir_path.mkdir(parents=True, exist_ok=True)
    n = len(list(dir_path.glob(f"{name_prefix}-*.json"))) + 1
    path = dir_path / f"{name_prefix}-{n:03d}.json"
    _atomic_write_text(
        path, json.dumps(accounting, indent=1, sort_keys=True) + "\n")
    return path


def purge_pursuit_memory(pursuit_root: Path, *, actor: str,
                         firm_store: KBStore | None = None) -> PurgeReport:
    """B69§1's other half made real (P17/C7): retained by default,
    PURGEABLE ON DEMAND. Deletes every card in the pursuit's memory
    lane, sweeps drafts/revisions that cited them (client-derived prose
    does not outlive its cards — the R8 rule applied to the lane), and
    proves the removal with a scan over the firm store and every other
    lane. Accounting-or-raise: every memory card must be accounted, and
    the accounting persists in the PURSUIT (it survives the lane it
    describes)."""
    pursuit_root = Path(pursuit_root)
    memory_root = pursuit_root / "memory"
    store = KBStore(memory_root)
    report = PurgeReport(client=f"pursuit:{pursuit_root.name}")
    all_ids = sorted(c["kb_id"] for c in store.list_cards())
    # Authorization UP FRONT and UNCONDITIONAL (P1-13): the restricted
    # gate logs and refuses before anything mutates — an empty lane still
    # answers to it, so no purge ever runs unlogged.
    store.restricted.authorize(actor, "purge", "delete")
    for kb_id in all_ids:
        store.delete_card(kb_id)
        store.restricted.delete(kb_id, actor=actor)
        report.purged.append(kb_id)

    accounting = {
        "pursuit": pursuit_root.name,
        "pursuit_memory_cards": report.purged,
        "drafts": [],
        "proposals": [],
        "lessons": [],
        "sweep_clean": False,
    }
    stub = PurgeAccounting(client=f"pursuit:{pursuit_root.name}")
    _sweep_drafts(pursuit_root.parent, set(report.purged), stub)
    accounting["drafts"] = stub.drafts
    if firm_store is not None:
        # P26c: the pursuit's proposals and the lessons they landed on
        # firm cards go with it (D1 at the carry-forward layer)
        accounting["proposals"], accounting["lessons"] = strip_carried_forward(
            firm_store, pursuit_root.name)

    # The accounting measures the FILESYSTEM after the delete (P1-13:
    # comparing the report to the list it was built from proved nothing).
    survivors = [kb_id for kb_id in all_ids if store.card_exists(kb_id)]
    if firm_store is not None:
        survivors += _carried_forward_survivors(firm_store, pursuit_root.name)
    if survivors:
        raise RuntimeError(
            f"pursuit-memory purge of {pursuit_root.name!r} left card(s) "
            f"in place: {survivors} — the accounting IS the deliverable")

    sweep_over = firm_store or KBStore(memory_root)  # at minimum, itself
    report.sweep_findings = post_purge_sweep(
        sweep_over, [], report.purged,
        extra_stores=_lane_stores(pursuit_root.parent))
    report.swept_clean = not report.sweep_findings
    accounting["sweep_clean"] = report.swept_clean
    path = _write_lane_accounting(pursuit_root / "purges", "memory",
                                  accounting)
    report.accounting = accounting
    report.accounting_path = str(path)
    if firm_store is not None:
        firm_store.restricted.log_sweep(actor=actor, client=report.client,
                                        clean=report.swept_clean,
                                        name=path.name)
    return report


def purge_org(workspace: Path, org_id: str, *, actor: str,
              firm_store: KBStore | None = None) -> PurgeReport:
    """Remove an organization's memory AND its identity record — the
    whole <workspace>/orgs/<org_id>/ tree (P17/C7). Org memory outlives
    pursuits by design, so only this explicit door takes it. The sweep
    scans every remaining lane for the purged okb_ ids AND every
    pursuit's brief for research findings that cited them — a frozen
    brief citing a purged note is a FINDING surfaced to the human, never
    silently rewritten (the record is immutable). Accounting persists in
    the workspace orgs dir under the OPAQUE id — org names die with
    org.json."""
    import shutil

    workspace = Path(workspace)
    org_dir = workspace / "orgs" / org_id
    if not (org_dir / "org.json").exists():
        raise RuntimeError(f"unknown org {org_id!r} — nothing to purge")
    store = KBStore(org_dir / "memory")
    report = PurgeReport(client=f"org:{org_id}")
    all_ids = sorted(c["kb_id"] for c in store.list_cards())
    # Authorization UP FRONT and UNCONDITIONAL (P1-13): the restricted
    # gate logs and refuses before anything is removed — an org with no
    # notes still answers to it (the same gate purge_client answers to).
    store.restricted.authorize(actor, "purge", "delete")
    for kb_id in all_ids:
        store.delete_card(kb_id)
        store.restricted.delete(kb_id, actor=actor)
        report.purged.append(kb_id)
    shutil.rmtree(org_dir)
    # The accounting measures the FILESYSTEM after the delete (P1-13).
    if org_dir.exists():
        raise RuntimeError(
            f"org purge of {org_id!r} left the org tree in place — the "
            "accounting IS the deliverable")

    findings = []
    if firm_store is not None:
        findings += post_purge_sweep(
            firm_store, [], report.purged,
            extra_stores=_lane_stores(workspace))
    else:
        for lane in _lane_stores(workspace):
            findings += post_purge_sweep(lane, [], report.purged)
    for brief_path in sorted(workspace.glob("*/brief*.json")):
        try:
            text = brief_path.read_text(encoding="utf-8")
        except OSError:
            continue
        findings += [
            f"{brief_path.parent.name}/{brief_path.name}: cites purged "
            f"org note {kb_id} (frozen records are surfaced, not rewritten)"
            for kb_id in report.purged if kb_id in text
        ]
    report.sweep_findings = findings
    report.swept_clean = not findings

    accounting = {
        "org_id": org_id,
        "org_cards": report.purged,
        "org_record_removed": True,
        "sweep_clean": report.swept_clean,
    }
    survivors = [kb_id for kb_id in all_ids
                 if (org_dir / "memory" / "cards" / f"{kb_id}.md").exists()]
    if survivors:
        raise RuntimeError(
            f"org purge of {org_id!r} left card(s) in place: {survivors} "
            "— the accounting IS the deliverable")
    path = _write_lane_accounting(workspace / "orgs", f"purge-{org_id}",
                                  accounting)
    report.accounting = accounting
    report.accounting_path = str(path)
    if firm_store is not None:
        firm_store.restricted.log_sweep(actor=actor, client=report.client,
                                        clean=report.swept_clean,
                                        name=path.name)
    return report
