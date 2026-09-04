"""Retrieval acceptance: 20 questions answered, retrievals reconstructable
from the run log alone, exclusions recorded, emitter discipline enforced.

The reconstruction test re-EXECUTES each logged query against the same
store and compares results — it does not trust the logged fields, it
proves them (the whole point of clause 5).
"""

import pytest

from engine.contracts import ContractError
from engine.kb import (
    KBStore,
    UseRestrictedCard,
    card_search,
    descend,
    emit_kb_retrieval,
    targeted_open,
)
from engine.runlog import RunLogger, read_run

from tests.kb.fixtures.corpus import ingest_corpus
from tests.kb.fixtures.questions import QUESTIONS


@pytest.fixture(scope="module")
def seeded(tmp_path_factory):
    root = tmp_path_factory.mktemp("kb-retrieval") / "kb"
    store, reports = ingest_corpus(root)
    assert all(r.status == "ingested" for r in reports)
    return store


def _marker_index(store: KBStore) -> dict[str, str]:
    index = {}
    for card in store.list_cards():
        _, body = store.read_card(card["kb_id"])
        for _, marker in QUESTIONS:
            if marker in body:
                assert marker not in index, f"marker {marker!r} is not unique"
                index[marker] = card["kb_id"]
    return index


def _log(store: KBStore, run_id: str) -> RunLogger:
    return RunLogger(store.root, run_id, "kb")


def test_card_search_answers_twenty_sample_questions(seeded):
    markers = _marker_index(seeded)
    log = _log(seeded, "run_0100")
    missed = []
    for question, marker in QUESTIONS:
        expected = markers[marker]
        result = card_search(seeded, question, log=log, stage="drafting",
                             agent="section_drafter")
        if expected not in [r.kb_id for r in result.results]:
            missed.append((question, marker))
    assert not missed, f"{len(missed)}/20 questions missed: {missed}"


def test_retrievals_reconstruct_from_run_log_alone(seeded):
    """P13/C11 extended: every retrieval MOVE replays from its line
    alone — bare searches, facet-filtered searches (the filter is ON the
    line), and path descents (the anchor rides in the query)."""
    log = _log(seeded, "run_0101")
    for question, _ in QUESTIONS[:5]:
        card_search(seeded, question, log=log, stage="drafting",
                    agent="section_drafter")
    card_search(seeded, QUESTIONS[0][0], log=log, stage="drafting",
                agent="section_drafter",
                facets={"section_types": ["data_migration"]})
    anchor = next(c["kb_id"] for c in seeded.list_cards()
                  if c.get("canonical_doc_id") and c.get("doc_path"))
    descend(seeded, anchor, "siblings", log=log, stage="drafting",
            agent="section_drafter")

    records = read_run(seeded.root / "runs" / "run_0101" / "run.jsonl")
    replayed = 0
    replay_log = _log(seeded, "run_0102")
    for record in records:
        if record["record_type"] != "kb_retrieval":
            continue
        kb = record["kb"]
        assert kb["query"] and kb["step"], "line is not reconstructable"
        if kb["step"] == "card_search":
            again = card_search(seeded, kb["query"], log=replay_log,
                                stage="drafting", agent="section_drafter",
                                facets=kb.get("facets"))
        elif kb["step"] == "path_descend":
            again = descend(seeded, kb["query"].split(":", 1)[1],
                            kb["relation"], log=replay_log,
                            stage="drafting", agent="section_drafter")
        else:
            continue
        assert [r.kb_id for r in again.results] == kb["cards_returned"]
        assert [e["kb_id"] for e in again.excluded] == kb["excluded"]
        replayed += 1
    assert replayed == 7


def test_facet_filter_narrows_without_moving_scores(seeded):
    """R9's cross-document move: the filter narrows candidates but the
    idf universe never shifts (the rank.py law) — a surviving card's
    score is identical filtered or not. And the heading path is NOT a
    facet: there is deliberately no way to filter by doc_path (KB10)."""
    log = _log(seeded, "run_0104")
    query = "how is legacy data converted and reconciled?"
    unfiltered = card_search(seeded, query, log=log, stage="drafting",
                             agent="section_drafter")
    filtered = card_search(seeded, query, log=log, stage="drafting",
                           agent="section_drafter",
                           facets={"section_types": ["data_migration"]})
    assert filtered.results, "the filtered search must still answer"
    for scored in filtered.results:
        assert "data_migration" in scored.card["section_types"]
    unfiltered_scores = {r.kb_id: r.score for r in unfiltered.results}
    for scored in filtered.results:
        if scored.kb_id in unfiltered_scores:
            assert scored.score == unfiltered_scores[scored.kb_id]
    records = read_run(seeded.root / "runs" / "run_0104" / "run.jsonl")
    line = [r for r in records if r["record_type"] == "kb_retrieval"][-1]
    assert line["kb"]["facets"] == {"section_types": ["data_migration"]}
    assert line["kb"]["catalog_size"] > 0


def test_exclude_does_not_move_scores(seeded):
    """M-29 (P26b-2): `exclude` is per-query, so it filters AFTER the
    idf computation like facets — a surviving card's score is identical
    with and without it, and the catalog size on the line (the idf
    corpus) does not shrink."""
    log = _log(seeded, "run_0199")
    query = "how is legacy data converted and reconciled?"
    plain = card_search(seeded, query, log=log, stage="drafting",
                        agent="section_drafter")
    assert len(plain.results) >= 2
    dropped = plain.results[0].kb_id
    narrowed = card_search(seeded, query, log=log, stage="drafting",
                           agent="section_drafter",
                           exclude=frozenset({dropped}))
    assert dropped not in {r.kb_id for r in narrowed.results}
    assert {"kb_id": dropped, "reason": "replay_excluded"} in narrowed.excluded
    plain_scores = {r.kb_id: r.score for r in plain.results}
    for scored in narrowed.results:
        if scored.kb_id in plain_scores:
            assert scored.score == plain_scores[scored.kb_id]
    records = read_run(seeded.root / "runs" / "run_0199" / "run.jsonl")
    lines = [r for r in records if r["record_type"] == "kb_retrieval"][-2:]
    assert lines[0]["kb"]["catalog_size"] == lines[1]["kb"]["catalog_size"]


def test_card_search_lines_carry_catalog_size(seeded):
    log = _log(seeded, "run_0105")
    card_search(seeded, QUESTIONS[0][0], log=log, stage="drafting",
                agent="section_drafter")
    records = read_run(seeded.root / "runs" / "run_0105" / "run.jsonl")
    line = [r for r in records if r["record_type"] == "kb_retrieval"][-1]
    searchable = sum(1 for c in seeded.list_cards()
                     if c.get("layer") != "fact_sheet"
                     and not c.get("use_restriction")
                     and not c.get("deprecated"))
    assert line["kb"]["catalog_size"] == searchable
    assert "facets" not in line["kb"], "an unfiltered line stays bare"


def test_emitter_enforces_query_step_and_subset_chain(seeded):
    log = _log(seeded, "run_0103")
    with pytest.raises(ContractError, match="query and step"):
        emit_kb_retrieval(log, stage="drafting", agent="a", query="",
                          step="card_search", cards_returned=[])
    with pytest.raises(ContractError, match="cards_opened"):
        emit_kb_retrieval(log, stage="drafting", agent="a", query="q",
                          step="card_search", cards_returned=[],
                          cards_opened=["kb_x"])
    with pytest.raises(ContractError, match="cards_cited"):
        emit_kb_retrieval(log, stage="drafting", agent="a", query="q",
                          step="card_search", cards_returned=["kb_x"],
                          cards_opened=["kb_x"], cards_cited=["kb_y"])


def test_targeted_open_returns_body_and_traces(seeded):
    markers = _marker_index(seeded)
    log = _log(seeded, "run_0106")
    kb_id = markers["rollback rehearsal"]
    body = targeted_open(seeded, kb_id, log=log, stage="drafting",
                         agent="section_drafter", query="cutover gates")
    assert "rollback rehearsal" in body
    line = read_run(seeded.root / "runs" / "run_0106" / "run.jsonl")[-1]
    assert line["kb"]["step"] == "targeted_open"
    assert line["kb"]["cards_opened"] == [kb_id]


def _tiny_store(tmp_path) -> KBStore:
    store = KBStore(tmp_path / "kb")
    prov = {"source_pursuit": "pur_x", "source_client": "Meridian Health Partners",
            "date": "2025-01-01", "ingested_by": "ingestion_agent"}
    store.write_card(
        {"kb_id": "kb_open000001", "layer": "corpus",
         "summary": "Payroll parallel testing approach for a utility.",
         "title": "Payroll parallels", "use_restriction": False,
         "canonical_block": True, "outcome": "won"},
        "Payroll parallel testing body.", prov, {})
    store.write_card(
        {"kb_id": "kb_restr00001", "layer": "corpus",
         "summary": "Payroll parallel testing approach, restricted client.",
         "title": "Payroll parallels (restricted)", "use_restriction": True,
         "outcome": "won"},
        "Restricted payroll body.", prov, {})
    return store


def test_use_restriction_withheld_and_recorded(tmp_path):
    store = _tiny_store(tmp_path)
    log = _log(store, "run_0001")
    result = card_search(store, "payroll parallel testing", log=log,
                         stage="drafting", agent="section_drafter")
    assert [r.kb_id for r in result.results] == ["kb_open000001"]
    assert result.excluded == [{"kb_id": "kb_restr00001",
                                "reason": "use_restriction"}]
    line = read_run(store.root / "runs" / "run_0001" / "run.jsonl")[-1]
    assert line["kb"]["excluded"] == ["kb_restr00001"]


def test_targeted_open_refuses_restricted_card(tmp_path):
    store = _tiny_store(tmp_path)
    log = _log(store, "run_0001")
    with pytest.raises(UseRestrictedCard):
        targeted_open(store, "kb_restr00001", log=log, stage="drafting",
                      agent="section_drafter", query="payroll")
    line = read_run(store.root / "runs" / "run_0001" / "run.jsonl")[-1]
    assert line["kb"]["excluded"] == ["kb_restr00001"]
    assert line["kb"]["cards_opened"] == []


def test_explicit_exclude_is_replay_hygiene(tmp_path):
    store = _tiny_store(tmp_path)
    log = _log(store, "run_0001")
    result = card_search(store, "payroll parallel testing", log=log,
                         stage="drafting", agent="section_drafter",
                         exclude=frozenset({"kb_open000001"}))
    assert result.results == []
    assert {"kb_id": "kb_open000001", "reason": "replay_excluded"} in result.excluded


def test_empty_result_is_success_with_flag(tmp_path):
    store = _tiny_store(tmp_path)
    log = _log(store, "run_0001")
    result = card_search(store, "quantum blockchain telemetry", log=log,
                         stage="drafting", agent="section_drafter")
    assert result.results == []
    line = read_run(store.root / "runs" / "run_0001" / "run.jsonl")[-1]
    assert line["kb"]["empty_result"] is True


def test_ranking_is_deterministic(seeded):
    log = _log(seeded, "run_0107")
    runs = [
        [r.kb_id for r in card_search(seeded, "payroll parallel testing",
                                      log=log, stage="drafting",
                                      agent="section_drafter").results]
        for _ in range(2)
    ]
    assert runs[0] == runs[1]


def test_canonical_block_rides_on_results(tmp_path):
    store = _tiny_store(tmp_path)
    log = _log(store, "run_0001")
    result = card_search(store, "payroll parallel testing", log=log,
                         stage="drafting", agent="section_drafter")
    canonical = [r for r in result.results if r.card.get("canonical_block")]
    assert [r.kb_id for r in canonical] == ["kb_open000001"]


def test_deprecated_withheld_and_recorded(tmp_path):
    """P26c (P1-43): an accepted deprecation lands as a `deprecated`
    block on the card, and retrieval honours it exactly as D2 — the card
    is withheld before idf (it is not in the catalog the scores come
    from), the exclusion is recorded on the trace with its reason, and
    the card is never deleted."""
    store = _tiny_store(tmp_path)
    store.update_card_front("kb_open000001", deprecated={
        "at": "2026-09-04T10:00:00Z", "by": "steward",
        "proposal_id": "prop_0123456789ab"})
    log = _log(store, "run_0001")
    result = card_search(store, "payroll parallel testing", log=log,
                         stage="drafting", agent="section_drafter")
    assert result.results == []
    assert {"kb_id": "kb_open000001", "reason": "deprecated"} in result.excluded
    line = read_run(store.root / "runs" / "run_0001" / "run.jsonl")[-1]
    assert sorted(line["kb"]["excluded"]) == ["kb_open000001", "kb_restr00001"]
    assert line["kb"]["catalog_size"] == 0, "withheld before idf"
    assert store.card_exists("kb_open000001"), "withheld, never deleted"
