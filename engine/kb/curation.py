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

from engine.contracts import ContractError, append_fsync, path_lock

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
    if card.get("deprecated"):
        notes.append("deprecated — withheld from retrieval, kept as the record")
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
            # P26c: the two homes an accepted proposal lands in ON a card,
            # visible from the row — a steward sees a lesson arrive.
            "lessons": list(card.get("lessons") or []),
            "deprecated": bool(card.get("deprecated")),
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
    proposal lane (deprecate or keep). One row per orphaned card, the
    LATEST reconciliation wins for its context — reports of one document
    are ordered by lineage length (P1-38: a later reconciliation carries
    a superset of priors), name as the tiebreak."""
    import json as _json

    recon_dir = store.root / "reconciliation"
    rows: dict[str, dict] = {}
    if recon_dir.is_dir():
        reports = [(path.name, _json.loads(path.read_text(encoding="utf-8")))
                   for path in recon_dir.glob("*.json")]
        reports.sort(key=lambda item: (len(item[1].get("prior_doc_ids", [])),
                                       item[0]))
        for _name, report in reports:
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

    Opt-in at answer time (the answerer asks for it) AND routed at
    accept for every answered gap no proposal carries yet (P26c, the
    owner's call at B116 §5); either way the proposal carries
    door=gap_answer + gap_id, and NOTHING enters the corpus until a
    steward accepts with owner/verified_date (the P13/C15 fill
    machinery — reused, not rebuilt)."""
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
    # P26c (P1-44): gap_id is the dedupe key between this opt-in door
    # and the accept-time route (B116 §5) — one answered gap, one
    # proposal, whoever proposed it; the operator is the human who
    # answered, when one is known.
    source = {"door": "gap_answer", "pursuit_id": pursuit_id,
              "gap_id": gap["gap_id"]}
    if operator:
        source["operator"] = operator
    proposal = ProposalStore(Path(kb_root)).open(
        source=source,
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
    card, body, derived_from = _check_new_card(store, proposal, fill)
    provenance = {
        "source_pursuit": (proposal.get("source") or {}).get("pursuit_id", ""),
        "ingested_by": f"steward:{operator}",
        "derived_from": list(derived_from),
    }
    store.write_card(card, body, provenance, {})
    return card["kb_id"]


def _check_new_card(store, proposal: dict, fill: dict) -> tuple[dict, str, list]:
    """Every refusal a new_card acceptance can raise, with NO write —
    the validation pass of merge_batch (P1-21) runs this for the whole
    batch before anything applies. Returns (card, body, derived_from)."""
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
        # P26c: a corpus case block keeps its own kind (case_study)
        "doc_kind": fields.get("doc_kind", "fact"),
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
    return card, body, derived_from


from engine.kb.notes import NOTE_KINDS  # noqa: E402 — one home for the vocabulary


def home_of(store, proposal: dict) -> dict:
    """P26c (P1-43): where an ACCEPTED proposal lands, named BEFORE the
    decision — the inbox shows it, pass 1 of merge_batch refuses a
    proposal with no home, pass 2 dispatches on it. Pure over
    store.card_exists (one stat per proposal; the listing calls it per
    row). Until this every kind outside update_card-with-fields and
    new_card was decided and changed nothing — the owner's call (B115
    §10): accepting something that is not carried forward is unexpected
    behaviour, so a proposal either has a home or refuses by name.

    kinds: card_field (front matter), card_lesson (a lessons entry on
    the cited card), note (the accepted proposal IS the steward note the
    drafter and the KB screen read — one home, no second copy to drift),
    deprecate (a deprecated block; retrieval withholds the card),
    new_card (needs_fill names what the steward must supply), none
    (refused typed — never decide-only)."""
    kind = proposal.get("kind")
    kb_id = proposal.get("kb_id")
    target = str(proposal.get("target") or "")
    diff = proposal.get("diff") or {}
    if kind == "update_card" and kb_id:
        if not store.card_exists(kb_id):
            return {"kind": "none", "needs_fill": [],
                    "label": f"{kb_id} no longer exists — nothing to update"}
        fields = sorted(set(diff) - {"text"})
        if fields:
            label = f"front matter of {kb_id} ({', '.join(fields)})"
            if "text" in diff:
                label += " and a lesson on the card"
            return {"kind": "card_field", "kb_id": kb_id, "label": label,
                    "needs_fill": []}
        if "text" in diff:
            return {"kind": "card_lesson", "kb_id": kb_id, "needs_fill": [],
                    "label": (f"a lesson on {kb_id} — steward-visible, "
                              "never drafted from")}
        return {"kind": "none", "needs_fill": [],
                "label": f"{kb_id}: an empty diff changes nothing"}
    if kind == "update_card" or kind in NOTE_KINDS:
        return {"kind": "note", "needs_fill": [],
                "label": f"a steward note under {target.replace('_', ' ')}"}
    if kind == "deprecate_card":
        if not kb_id or not store.card_exists(kb_id):
            return {"kind": "none", "needs_fill": [],
                    "label": f"{kb_id or 'no card'} no longer exists — "
                             "nothing to deprecate"}
        return {"kind": "deprecate", "kb_id": kb_id, "needs_fill": [],
                "label": f"deprecate {kb_id} — withheld from retrieval, "
                         "never deleted"}
    if kind == "new_card":
        layer = (diff.get("layer") or {}).get("after", "fact_sheet")
        needs = ["owner", "verified_date"] if layer == "fact_sheet" else []
        return {"kind": "new_card", "needs_fill": needs,
                "label": f"a new {str(layer).replace('_', ' ')} card"}
    return {"kind": "none", "needs_fill": [],
            "label": (f"no home for {kind!r} until the win/loss backlabel "
                      "lands (P3-4)")}


def _lesson_entry(proposal: dict, text, *, by: str, at: str) -> dict:
    """The lessons[] record an accepted flywheel edit becomes (P26c):
    the reviewer's prose, the events and pursuit it came from, the
    steward who accepted it. `after` is the lesson; without it there is
    nothing to carry."""
    if not isinstance(text, dict) or not text.get("after"):
        raise CurationRefused(
            f"{proposal['proposal_id']}: a lesson needs diff.text.after — "
            f"nothing to carry onto the card")
    source = proposal.get("source") or {}
    entry = {"at": at, "by": by, "proposal_id": proposal["proposal_id"],
             "after": str(text["after"])}
    if text.get("before") is not None:
        entry["before"] = str(text["before"])
    for key in ("pursuit_id", "event_ids", "external"):
        if source.get(key) is not None:
            entry[key] = source[key]
    if proposal.get("note"):
        entry["note"] = proposal["note"]
    return entry


def merge_batch(store, proposal_ids: list[str], *, operator: str,
                at: str, fills: dict | None = None) -> dict:
    """A steward's merge: one batch, one curation-log line, one snapshot
    pair. v1's shape — batching is what makes 'what changed and when'
    answerable without replaying forty individual decisions.

    `fills` (P13/C15): {proposal_id: {owner, verified_date, …}} — the
    steward-supplied fields a new_card acceptance requires.

    The whole batch — the status checks, the writes, the decisions and
    the log line — is ONE critical section under the KB root's lock
    (P1-40): two stewards merging at once used to interleave, and both
    snapshot pairs lied."""
    with path_lock(store.root):
        return _merge_batch_locked(store, proposal_ids, operator=operator,
                                   at=at, fills=fills)


def _merge_batch_locked(store, proposal_ids: list[str], *, operator: str,
                        at: str, fills: dict | None = None) -> dict:
    """Two passes (P1-21). Pass 1 validates the WHOLE batch and writes
    nothing: every proposal is `proposed` and HAS A HOME (P26c, P1-43 —
    `home_of`; a kind with no home refuses by name instead of deciding
    and changing nothing), every card update targets a card that exists
    and would still validate with the change applied (a dry run of the
    write — a lesson is dry-run into lessons[] the same way; an unknown
    diff key is refused here, never written), every deprecation names a
    card that exists and is not held, every new card passes its checks
    with its fill. A refusal applies nothing, decides nothing, logs
    nothing. Pass 2 applies — front matter, the lesson, the deprecated
    block, the new card; a note kind writes nothing because the accepted
    record IS the note (engine/kb/notes.py reads it) — and if it dies
    mid-way the curation-log line is still written naming what applied
    and why it stopped."""
    import json

    from engine.contracts import validate

    proposals = ProposalStore(store.root)
    fills = fills or {}
    staged: list[tuple[str, dict, dict, dict, dict | None]] = []
    for pid in proposal_ids:
        proposal = proposals.read(pid)
        if proposal["status"] != "proposed":
            raise CurationRefused(
                f"{pid} is already {proposal['status']} — a decision is "
                f"made once")
        home = home_of(store, proposal)
        if home["kind"] == "none":
            raise CurationRefused(
                f"{pid}: {home['label']} — refused before anything applied")
        fields: dict = {}
        lesson: dict | None = None
        if home["kind"] in ("card_field", "card_lesson"):
            kb_id = proposal["kb_id"]
            changes = dict(proposal.get("diff") or {})
            text = changes.pop("text", None)
            fields = {name: change["after"] for name, change in changes.items()}
            card, _body = store.read_card(kb_id)
            dry = {**card, **fields}
            if text is not None:
                lesson = _lesson_entry(proposal, text, by=operator, at=at)
                dry["lessons"] = [*(card.get("lessons") or []), lesson]
            try:
                validate("kb_card", dry)
            except ContractError as exc:
                raise CurationRefused(
                    f"{pid}: the change does not fit {kb_id}'s front "
                    f"matter ({exc}) — refused before anything applied"
                ) from exc
        elif home["kind"] == "deprecate":
            card, _body = store.read_card(proposal["kb_id"])
            if card.get("legal_hold"):
                raise CurationRefused(
                    f"{pid}: {proposal['kb_id']} is under legal hold and "
                    f"cannot be deprecated")
        elif home["kind"] == "new_card":
            _check_new_card(store, proposal, fills.get(pid) or {})
        staged.append((pid, proposal, home, fields, lesson))

    snapshot_before = store.snapshot()
    accepted: list[str] = []
    aborted: str | None = None
    try:
        for pid, proposal, home, fields, lesson in staged:
            if fields:
                store.update_card_front(proposal["kb_id"], **fields)
            if lesson is not None:
                store.append_lesson(proposal["kb_id"], lesson)
            if home["kind"] == "deprecate":
                store.update_card_front(
                    proposal["kb_id"],
                    deprecated={"at": at, "by": operator, "proposal_id": pid})
            elif home["kind"] == "new_card":
                _apply_new_card(store, proposal, fills.get(pid) or {},
                                operator)
            proposals.decide(pid, decision="accepted", by=operator, at=at)
            accepted.append(pid)
    except BaseException as exc:  # noqa: BLE001 — logged, then re-raised
        aborted = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        line = {"at": at, "by": operator, "proposal_ids": accepted,
                "snapshot_before": snapshot_before,
                "snapshot_after": store.snapshot()}
        if aborted is not None:
            line["aborted"] = aborted
        log = store.root / "curation-log.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        append_fsync(log, json.dumps(line, sort_keys=True))  # P0-6
    return line
