"""Retrieval: card_search + targeted_open, every call traced (O2).

Two-step agentic search (K3/K4): card_search ranks the catalog — title,
summary, facet tags; a few hundred tokens per card — and targeted_open
reads one card's full body. Token cost scales with relevance, not corpus
size. Embeddings are a later accelerator behind this same seam.

emit_kb_retrieval is the choke point: both tools emit through it, and it
refuses a line the run log could not reconstruct — query and step are
mandatory, and cards_cited ⊆ cards_opened ⊆ cards_returned or the emit
raises (the B10 pattern: the schema requires the kb payload's PRESENCE,
code enforces its discipline). A retrieval that finds nothing SUCCEEDED
and returns [] — the caller, not the store, decides what empty means.

use_restriction (D2) is honored here: a restricted card is withheld from
results and its kb_id RECORDED in kb.excluded, so a gap can explain itself
at Gate 2 instead of shrugging. canonical_block rides on every returned
card for its P7 consumer.

Search's replay rule, generalized at P13/C11 (WP13 R9): THE LINE IS
SUFFICIENT. The original design took a bare query string so any logged
retrieval replays from the run log alone; the second retrieval move
keeps that law by putting everything the move used ON the line — the
facet filter on card_search lines, the anchor + relation on
path_descend lines. A retrieval that cannot be reconstructed from its
own line does not get emitted.

path_descend is the within-document move: siblings, parent, or children
of a card, read from its canonical model's chunk backrefs — ONE file
read, no catalog scan by construction (R9). The heading path is
navigation only, never a retrieval key (KB10). A pre-WP13 card has no
canonical model and descends to a recorded empty result, never an
error (R11).
"""

from dataclasses import dataclass, field

from engine.contracts import ContractError
from engine.kb.canonical import model_path, read_model
from engine.kb.lanes import Lanes, as_lanes
from engine.kb.rank import DEFAULT_K, bm25_score, idf_weights, tokenize
from engine.kb.store import KBStore


class UseRestrictedCard(LookupError):
    """targeted_open refused a use_restriction card (D2)."""


@dataclass
class ScoredCard:
    kb_id: str
    score: float
    card: dict


@dataclass
class SearchResult:
    results: list[ScoredCard] = field(default_factory=list)
    excluded: list[dict] = field(default_factory=list)  # {kb_id, reason}


def emit_kb_retrieval(log, *, stage, agent, query, step, cards_returned,
                      cards_opened=(), cards_cited=(), excluded=(),
                      empty_result=None, target=None, facets=None,
                      path=None, relation=None, catalog_size=None,
                      lanes=None, org_id=None) -> int:
    """The one emitter for kb_retrieval lines. Raises ContractError on any
    line that could not be reconstructed or that claims an impossible
    trajectory. The P13 fields (facets, path, relation, catalog_size)
    appear ONLY when set, so pre-P13 lines stay byte-identical — and the
    P17 fields (lanes, org_id) follow the same rule, so firm-only lines
    stay byte-identical too. Replay resolution for lane lines (B75§3a):
    lanes absent -> firm store; "pursuit" -> the line's pursuit_id's
    memory store; "org" -> the line's org_id's store."""
    if not query or not step:
        raise ContractError("kb_retrieval line requires query and step")
    returned, opened, cited = list(cards_returned), list(cards_opened), list(cards_cited)
    if not set(cited) <= set(opened):
        raise ContractError("kb_retrieval: cards_cited must be ⊆ cards_opened")
    if not set(opened) <= set(returned):
        raise ContractError("kb_retrieval: cards_opened must be ⊆ cards_returned")
    kb = {
        "query": query,
        "step": step,
        "cards_returned": returned,
        "cards_opened": opened,
        "cards_cited": cited,
        "excluded": list(excluded),
        "empty_result": not returned if empty_result is None else empty_result,
    }
    if facets:
        kb["facets"] = {name: list(values) for name, values in facets.items()}
    if path is not None:
        kb["path"] = list(path)
    if relation is not None:
        kb["relation"] = relation
    if catalog_size is not None:
        kb["catalog_size"] = catalog_size
    if lanes:
        kb["lanes"] = list(lanes)
    if org_id is not None:
        kb["org_id"] = org_id
    fields = {"stage": stage, "agent": agent, "kb": kb}
    if target:
        fields["target"] = target
    return log.emit("kb_retrieval", **fields)


def _catalog_text(card: dict) -> str:
    # question_forms (P17/C5): findable — they join the SCORED text —
    # never quotable: they live in frontmatter only, so targeted_open's
    # body return and every drafting frame never contain them (X10
    # posture, named test). Absent on the committed corpus, so its
    # scores are byte-stable (B75§4a).
    return " ".join([
        card.get("title", ""), card.get("summary", ""),
        " ".join(card.get("type_tags", [])),
        " ".join(card.get("section_types", [])),
        " ".join(card.get("question_forms", [])),
    ])


def _matches_facets(card: dict, facets: dict) -> bool:
    return all(set(card.get(name, ())) & set(values)
               for name, values in facets.items())


def card_search(store: KBStore | Lanes, query: str, *, log, stage, agent,
                k: int = DEFAULT_K, exclude: frozenset = frozenset(),
                target: dict | None = None,
                facets: dict | None = None) -> SearchResult:
    """Rank the card catalog for a query. Withheld cards (use_restriction,
    or explicit `exclude` ids — replay hygiene) are recorded, never silently
    dropped.

    `facets` (P13/C11, R9's cross-document move) narrows candidates to
    cards sharing at least one value per named facet — a code-side
    filter applied AFTER the idf computation, so corpus statistics never
    shift with the filter (the rank.py law) — and rides the emitted line
    so the filtered search replays from the log alone.

    `store` may be a Lanes bundle (P17/C3): the search runs over the
    UNION of the joined catalogs with ONE idf — a lane join is a
    different corpus, constant for the pursuit's life, not a per-query
    filter (B75§3b). The joined lane names and org_id ride the line;
    firm-only searches stay byte-identical to the pre-P17 shape."""
    lanes = as_lanes(store)
    facets = facets or {}
    result = SearchResult()
    active: list[tuple[dict, list[str]]] = []
    for _lane_name, lane_store in lanes.stores():
        for card in lane_store.list_cards():
            if card.get("layer") == "fact_sheet":
                # Verification ground truth, not drafting material (B34(26)):
                # surfacing the fact sheet to retrieval would let the drafter
                # condition on the Claim Auditor's answer key. Out of the
                # searchable universe entirely — before the idf computation so
                # fact cards never shift any score, and NOT an excluded row
                # (those record refusals of otherwise-eligible cards).
                continue
            if card["kb_id"] in exclude:
                result.excluded.append({"kb_id": card["kb_id"], "reason": "replay_excluded"})
                continue
            if card.get("use_restriction"):
                result.excluded.append({"kb_id": card["kb_id"], "reason": "use_restriction"})
                continue
            active.append((card, tokenize(_catalog_text(card))))

    idf = idf_weights([tokens for _, tokens in active])
    query_tokens = tokenize(query)
    eligible = (active if not facets
                else [(c, t) for c, t in active if _matches_facets(c, facets)])
    scored = sorted(
        ((bm25_score(query_tokens, tokens, idf), card) for card, tokens in eligible),
        # B15 (P13/C12): observed survival breaks score ties before
        # kb_id — deterministic tie-breaking only, never ranker tuning
        # (that calibration stays deferred, B41(1)/B46).
        key=lambda pair: (-pair[0],
                          -(pair[1].get("edit_survival") or 0.0),
                          pair[1]["kb_id"]),
    )
    result.results = [
        ScoredCard(kb_id=card["kb_id"], score=score, card=card)
        for score, card in scored[:k] if score > 0
    ]
    emit_kb_retrieval(
        log, stage=stage, agent=agent, query=query, step="card_search",
        cards_returned=[r.kb_id for r in result.results],
        excluded=[e["kb_id"] for e in result.excluded],
        target=target, facets=facets or None, catalog_size=len(active),
        lanes=lanes.joined() or None,
        org_id=lanes.org_id if lanes.org is not None else None,
    )
    return result


def descend(store: KBStore, kb_id: str, relation: str, *, log, stage,
            agent, target: dict | None = None) -> SearchResult:
    """The within-document move (P13/C11, R9): the anchor card's parent,
    siblings, or children, read from its canonical model's chunk
    backrefs — one file read, never a catalog scan. Results come back in
    DOCUMENT order, scoreless (this is navigation, not ranking — KB10).
    A pre-WP13 card, or one whose model is gone, descends to a recorded
    empty result (R11). use_restriction is honored exactly as in search.
    """
    if relation not in ("parent", "siblings", "children"):
        raise ContractError(f"descend: unknown relation {relation!r}")
    # A Lanes bundle dispatches to the lane that minted the anchor id —
    # the prefix IS the replay resolution, so descend lines stay bare.
    store = as_lanes(store).store_for(kb_id)
    query = f"descend:{kb_id}"  # the line carries the anchor — replayable
    card, _body = store.read_card(kb_id)
    cd = card.get("canonical_doc_id")
    path = list(card.get("doc_path") or ())
    result = SearchResult()
    if not cd or not model_path(store.root, cd).exists():
        emit_kb_retrieval(
            log, stage=stage, agent=agent, query=query, step="path_descend",
            cards_returned=[], empty_result=True, target=target,
            path=path, relation=relation)
        return result

    model = read_model(store.root, cd)
    depth = len(path)
    neighbor_ids: list[str] = []
    for chunk in model.chunks:
        if chunk.kb_id is None or chunk.kb_id == kb_id:
            continue
        chunk_path = list(chunk.doc_path)
        if relation == "parent":
            keep = depth > 0 and chunk_path == path[:-1]
        elif relation == "siblings":
            keep = (len(chunk_path) == depth
                    and chunk_path[:-1] == path[:-1])
        else:  # children
            keep = (len(chunk_path) == depth + 1
                    and chunk_path[:depth] == path)
        if keep and chunk.kb_id not in neighbor_ids:
            neighbor_ids.append(chunk.kb_id)

    for neighbor_id in neighbor_ids:
        if not store.card_exists(neighbor_id):
            continue  # absorbed or purged since the model was written
        neighbor, _ = store.read_card(neighbor_id)
        if neighbor.get("use_restriction"):
            result.excluded.append({"kb_id": neighbor_id,
                                    "reason": "use_restriction"})
            continue
        result.results.append(
            ScoredCard(kb_id=neighbor_id, score=0.0, card=neighbor))

    emit_kb_retrieval(
        log, stage=stage, agent=agent, query=query, step="path_descend",
        cards_returned=[r.kb_id for r in result.results],
        excluded=[e["kb_id"] for e in result.excluded],
        target=target, path=path, relation=relation)
    return result


def targeted_open(store: KBStore, kb_id: str, *, log, stage, agent,
                  query: str, target: dict | None = None) -> str:
    """Open one card's full body. A use_restriction card refuses loudly and
    the refusal is on the trace (D2). A Lanes bundle opens from the lane
    that minted the id (prefix dispatch, P17/C3)."""
    card, body = as_lanes(store).store_for(kb_id).read_card(kb_id)
    if card.get("use_restriction"):
        emit_kb_retrieval(
            log, stage=stage, agent=agent, query=query, step="targeted_open",
            cards_returned=[], excluded=[kb_id], empty_result=True,
            target=target,
        )
        raise UseRestrictedCard(
            f"{kb_id} carries use_restriction (D2) and may not be opened"
        )
    emit_kb_retrieval(
        log, stage=stage, agent=agent, query=query, step="targeted_open",
        cards_returned=[kb_id], cards_opened=[kb_id], target=target,
    )
    return body
