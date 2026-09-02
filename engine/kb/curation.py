"""The curation read models and doors (c20).

v1's governance spine, reimplemented: every edit door produces a
proposal, a steward merges, nothing is erased, and restricted material
is shown as an inline honesty NOTE rather than hidden behind a filter —
a reviewer who cannot see that a card is restricted cannot reason about
why it never appears in drafts.

v1's screen failures, fixed here: it had no search, no filter and no
sort at any scale; no in-place edit (only "propose a superseding copy");
and — the one that actually bit — no web route for approval at all, so
imported content sat published, valid and invisible to every draft while
the only approve door was a terminal command. Mint and approve ship on
the same surface, in the same slice.
"""

from pathlib import Path

from engine.contracts import append_fsync

from engine.flywheel.proposals import ProposalStore

STALE_SOON_DAYS = 90


def honesty_notes(card: dict) -> list[str]:
    """What a curator must be told about a card, inline. Never the
    restricted CONTENT — that stays behind the access log (S8) — only
    the fact of it, so absence from a draft is explainable."""
    notes = []
    if card.get("use_restriction"):
        notes.append("reuse restricted — never offered to drafting")
    if card.get("legal_hold"):
        notes.append("legal hold — cannot be deprecated or purged")
    if card.get("sensitivity") == "restricted":
        notes.append("restricted sensitivity — provenance is access-logged")
    if card.get("canonical_block"):
        notes.append("approved boilerplate — drafting reproduces it near-verbatim")
    if card.get("layer") == "fact_sheet":
        notes.append("fact sheet — verification ground truth, never drafting material")
    if card.get("outcome") == "lost":
        notes.append("from a lost pursuit — usable, but say so when it matters")
    return notes


def staleness(card: dict, *, at: str) -> str | None:
    """past_due | due_soon | None. Governed facts carry review_due; a
    card past it is still retrievable and says so rather than silently
    ageing out."""
    due = card.get("review_due")
    if not due:
        return None
    today = at[:10]
    if str(due) < today:
        return "past_due"
    from datetime import date
    try:
        delta = (date.fromisoformat(str(due)) - date.fromisoformat(today)).days
    except ValueError:
        return None
    return "due_soon" if delta <= STALE_SOON_DAYS else None


def cards_view(store, *, q: str = "", layer: str = "", staleness_filter: str = "",
               sort: str = "kb_id", at: str) -> list[dict]:
    """Search, filter and sort — the three things v1's grid lacked, which
    made it a viewer rather than a curation surface."""
    rows = []
    needle = q.strip().lower()
    for card in store.list_cards():
        if layer and card.get("layer") != layer:
            continue
        haystack = " ".join(str(card.get(f, "")) for f in
                            ("kb_id", "title", "summary", "owner"))
        if needle and needle not in haystack.lower():
            continue
        state = staleness(card, at=at)
        if staleness_filter and state != staleness_filter:
            continue
        rows.append({
            "kb_id": card["kb_id"],
            "layer": card.get("layer"),
            "doc_kind": card.get("doc_kind"),
            "title": card.get("title") or card["kb_id"],
            "summary": card.get("summary", ""),
            "owner": card.get("owner"),
            "review_due": card.get("review_due"),
            "staleness": state,
            "edit_survival": card.get("edit_survival"),
            "notes": honesty_notes(card),
        })
    reverse = sort in ("edit_survival",)
    rows.sort(key=lambda r: (r.get(sort) is None, r.get(sort) or ""),
              reverse=reverse)
    return rows


def card_detail(store, kb_id: str, *, records=None, at: str) -> dict:
    """One card, with the two things a curator judges by: how often the
    engine actually CITED it, and what would stop grounding if it went
    away. Impact is computed live and never persisted — the pack moves
    underneath, and a stored answer would age into a lie (v1's rule)."""
    card, body = store.read_card(kb_id)
    cited_in = []
    for record in records or ():
        if record.get("record_type") != "kb_retrieval":
            continue
        kb = record["kb"]
        if kb.get("step") == "cite" and kb_id in (kb.get("cards_cited") or ()):
            cited_in.append({
                "pursuit_id": record["pursuit_id"],
                "section_id": (record.get("target") or {}).get("section_id"),
            })
    return {
        "card": card,
        "body": body,
        "notes": honesty_notes(card),
        "staleness": staleness(card, at=at),
        "cited_in": cited_in,
        "cite_count": len(cited_in),
    }


def chunk_size_distribution(store) -> dict:
    """The R5/C19 diagnostic, observable on demand: chunk sizes are
    recorded on every card's chunk_span and NEVER enforced — an outlier
    here is an extraction finding to investigate (a forty-page chunk
    means sections were merged), not content to split (KB5: re-chunking
    orphans edit_survival)."""
    sizes = sorted(
        card["chunk_span"]["chars"] for card in store.list_cards()
        if card.get("chunk_span", {}).get("chars") is not None)
    if not sizes:
        return {"n": 0}

    def percentile(p: float) -> int:
        return sizes[min(len(sizes) - 1, int(p * len(sizes)))]

    return {"n": len(sizes), "min": sizes[0], "p50": percentile(0.5),
            "p95": percentile(0.95), "max": sizes[-1],
            "total_chars": sum(sizes)}


def orphans_view(store) -> list[dict]:
    """The steward's orphan review queue (P13/C9, R6: orphans are
    reviewed, not dropped). An orphan is a card a re-ingestion of its
    document no longer covers — retained in the store, listed from the
    persisted reconciliation reports, resolved through the existing
    proposal lane (deprecate or keep). One row per orphaned card, newest
    report wins for its reconciliation context."""
    import json as _json

    recon_dir = store.root / "reconciliation"
    rows: dict[str, dict] = {}
    if recon_dir.is_dir():
        for path in sorted(recon_dir.glob("*.json")):
            report = _json.loads(path.read_text(encoding="utf-8"))
            for kb_id in report.get("orphaned", []):
                if not store.card_exists(kb_id):
                    continue  # deprecated since — no longer a queue item
                card, _body = store.read_card(kb_id)
                rows[kb_id] = {
                    "kb_id": kb_id,
                    "title": card.get("title", ""),
                    "doc_id": report["doc_id"],
                    "canonical_doc_id": report["canonical_doc_id"],
                    "edit_survival": card.get("edit_survival"),
                }
    return [rows[k] for k in sorted(rows)]


class CurationRefused(ValueError):
    """A curation action the governance rules do not allow."""


def propose_edit(store, kb_id: str, changes: dict, *, operator: str,
                 at: str, note: str = "", door: str = "card_edit") -> dict:
    """In-place edit — as a PROPOSAL (S4). v1 had no in-place edit at
    all; you proposed a superseding copy, which is a heavier act than
    fixing a typo deserves. `door` (P14/B63) names the mechanism that
    opened it — the curation screen by default, "assistant" when the
    steward assistant drafts on the operator's instruction; the operator
    stays the human either way."""
    from engine.kb.xlsx import READ_ONLY

    card, _body = store.read_card(kb_id)
    locked = sorted(set(changes) & READ_ONLY)
    if locked:
        raise CurationRefused(
            f"{', '.join(locked)} is a governance decision or an "
            f"engine-derived value, not an edit — change it through the "
            f"lane that owns it")
    diff = {name: {"before": card.get(name), "after": value}
            for name, value in changes.items() if card.get(name) != value}
    if not diff:
        raise CurationRefused("nothing changed")
    return ProposalStore(store.root).open(
        source={"door": door, "operator": operator},
        target="fact_sheet" if card.get("layer") == "fact_sheet" else "corpus",
        kind="update_card", at=at, kb_id=kb_id, diff=diff,
        note=note or f"Edited on the curation screen by {operator}.")


def propose_deprecation(store, kb_id: str, *, operator: str, at: str,
                        records=None, note: str = "",
                        door: str = "deprecate") -> dict:
    """Delete means DEPRECATE, and it is refused while the card is still
    cited — with the citing pursuit NAMED, because "something depends on
    this" is unactionable without knowing what."""
    card, _body = store.read_card(kb_id)
    if card.get("legal_hold"):
        raise CurationRefused(
            f"{kb_id} is under legal hold and cannot be deprecated")
    detail = card_detail(store, kb_id, records=records, at=at)
    if detail["cited_in"]:
        citing = sorted({c["pursuit_id"] for c in detail["cited_in"]})
        raise CurationRefused(
            f"{kb_id} is cited by {', '.join(citing)} — deprecating it "
            f"would strand those citations. Supersede it instead, or "
            f"deprecate once those responses are closed")
    return ProposalStore(store.root).open(
        source={"door": door, "operator": operator},
        target="corpus", kind="deprecate_card", at=at, kb_id=kb_id,
        diff={"status": {"before": "active", "after": "deprecated"}},
        note=note or f"Deprecation proposed by {operator}.")


def propose_gap_answer_card(kb_root, *, gap: dict, pursuit_id: str,
                            operator: str, at: str) -> str:
    """P15/C10 (B69 §7, B70(1)): an ANSWERED intake gap may spawn a
    new_card proposal through the steward door — the missing link
    between "a human answered a question" and "the corpus learns", so
    the same question stops being re-asked pursuit after pursuit.

    OPT-IN, never automatic: the answerer asks for it, the proposal
    carries door=gap_answer + the operator, and NOTHING enters the
    corpus until a steward accepts with owner/verified_date (the
    P13/C15 fill machinery — reused, not rebuilt)."""
    if gap.get("status") != "answered" or not gap.get("answer"):
        raise CurationRefused(
            f"gap {gap.get('gap_id')!r} is not answered — only an "
            f"answered gap proposes a card")
    question = gap["question_to_human"]
    diff = {
        "title": {"after": question[:80]},
        "body": {"after": f"Q: {question}\nA: {gap['answer']}"},
        "layer": {"after": "fact_sheet"},
        "grain": {"after": "atom"},
        "content_origin": {"after": "source_text"},
    }
    proposal = ProposalStore(Path(kb_root)).open(
        source={"door": "gap_answer", "pursuit_id": pursuit_id,
                "operator": operator},
        target="fact_sheet", kind="new_card", at=at, diff=diff,
        note=(f"Answered intake gap {gap['gap_id']} "
              f"(answered by {gap.get('answered_by', operator)}). A "
              f"steward must supply owner and verified_date at "
              f"acceptance."))
    return proposal["proposal_id"]


def _apply_new_card(store, proposal: dict, fill: dict,
                    operator: str) -> str:
    """Execute an accepted new_card proposal (P13/C15 — until now,
    accepting one silently wrote nothing). The card mints content-
    anchored; a fact-sheet card REFUSES acceptance until the steward
    supplies owner + verified_date in `fill` — the machine drafted the
    claim, a human vouches for it (the owner's call, B59). The purge link
    rides derived_from (the source chunk card), so the atom cascades
    with its client without the proposal ever naming one."""
    from engine.kb.identity import kb_id_for
    from engine.kb.ingest import _placeholders_used

    fields = {name: change["after"]
              for name, change in (proposal.get("diff") or {}).items()}
    body = fields.pop("body", "")
    derived_from = fields.pop("derived_from", [])
    if not body:
        raise CurationRefused(
            f"{proposal['proposal_id']}: a new_card proposal without a "
            f"body mints nothing")
    card = {
        "kb_id": kb_id_for(body),
        "layer": fields.get("layer", "fact_sheet"),
        "doc_kind": "fact",
        "title": fields.get("title", body.splitlines()[0][:80]),
        "summary": fields.get("title", body.splitlines()[0][:80]),
        "grain": fields.get("grain", "atom"),
        "content_origin": fields.get("content_origin", "source_text"),
        "sensitivity": "internal",
        "anonymization": {"status": "anonymized",
                          "placeholders_used": _placeholders_used(body)},
        "version": 1,
    }
    for key in ("owner", "verified_date", "review_due"):
        if key in fill:
            card[key] = fill[key]
    if (card["layer"] == "fact_sheet"
            and not (card.get("owner") and card.get("verified_date"))):
        raise CurationRefused(
            f"{proposal['proposal_id']}: a fact card needs owner and "
            f"verified_date from the accepting steward — supply them in "
            f"fills (nothing is verified until a human vouches for it)")
    if store.card_exists(card["kb_id"]):
        raise CurationRefused(
            f"{proposal['proposal_id']}: {card['kb_id']} already exists "
            f"— this content is already in the store")
    provenance = {
        "source_pursuit": (proposal.get("source") or {}).get("pursuit_id", ""),
        "ingested_by": f"steward:{operator}",
        "derived_from": list(derived_from),
    }
    store.write_card(card, body, provenance, {})
    return card["kb_id"]


def merge_batch(store, proposal_ids: list[str], *, operator: str,
                at: str, fills: dict | None = None) -> dict:
    """A steward's merge: one batch, one curation-log line, one snapshot
    pair. v1's shape — batching is what makes 'what changed and when'
    answerable without replaying forty individual decisions.

    `fills` (P13/C15): {proposal_id: {owner, verified_date, …}} — the
    steward-supplied fields a new_card acceptance requires."""
    import json

    proposals = ProposalStore(store.root)
    snapshot_before = store.snapshot()
    accepted = []
    fills = fills or {}
    for pid in proposal_ids:
        proposal = proposals.read(pid)
        if proposal["status"] != "proposed":
            raise CurationRefused(
                f"{pid} is already {proposal['status']} — a decision is "
                f"made once")
        if proposal["kind"] == "update_card" and proposal.get("kb_id"):
            fields = {name: change["after"]
                      for name, change in (proposal.get("diff") or {}).items()}
            if fields:
                store.update_card_front(proposal["kb_id"], **fields)
        elif proposal["kind"] == "new_card":
            _apply_new_card(store, proposal, fills.get(pid) or {}, operator)
        proposals.decide(pid, decision="accepted", by=operator, at=at)
        accepted.append(pid)

    line = {"at": at, "by": operator, "proposal_ids": accepted,
            "snapshot_before": snapshot_before,
            "snapshot_after": store.snapshot()}
    log = store.root / "curation-log.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    append_fsync(log, json.dumps(line, sort_keys=True))  # P0-6
    return line
