"""C12 (P13) — B15 lands at its corrected site (B46 item 10): observed
edit_survival is the first survivor key in dedup-merge and the score
tie-break in retrieval. A measurement is never discarded."""

import json

from engine.kb import KBStore, SourceDoc, card_search, ingest_document
from engine.kb.ingest import _survivor_is_candidate
from engine.llm import FakeCaller, TracedCaller
from engine.runlog import RunLogger

BODY = ("The migration factory converts legacy balances wave by wave "
        "with penny-level reconciliation against the source ledger.")
# A substitution variant, NOT an extension: one term swapped, so the
# forward overlap clears DEDUP_FLOOR but neither direction reaches 1.0
# — the containment override (C8) stays out of the way and the survivor
# tie-break decides. (Scores derived against the real tokenizer/idf:
# fwd 0.77, rev 0.94.)
BODY_VARIANT = ("The migration factory converts legacy balances wave by "
                "wave with cent-level reconciliation against the source "
                "ledger.")
# An extension: BODY verbatim (final token included — the tokenizer
# keeps punctuation) plus a vocabulary-reusing clause, so fwd 0.83 and
# rev exactly 1.0 — the containment override fires and the container
# survives regardless of tie-breaks.
BODY_EXTENDED = ("The migration factory converts legacy balances wave by "
                 "wave with penny-level reconciliation against the source "
                 "ledger. Reconciliation runs wave by wave against the "
                 "source ledger.")


def _wire(n: int) -> str:
    return json.dumps({
        "chunk_annotations": [
            {"chunk": i, "summary": "Migration approach exemplar.",
             "section_types": ["data_migration"],
             "type_tags": ["data_migration"]} for i in range(n)],
        "qa_pairs": [], "identifiers": [],
        "client_descriptor": "a synthetic firm",
    })


def _ingest(store, doc_id, body, outcome, run):
    log = RunLogger(store.root, run, "kb")
    caller = TracedCaller(FakeCaller({"ingestion_agent": _wire(1)}), log)
    doc = SourceDoc(
        doc_id=doc_id, text=f"# DOC:{doc_id}\n\n## Data Migration\n\n{body}\n",
        source_client="Foxfire", source_pursuit=f"pur_{doc_id}",
        outcome=outcome, date="2026-08-01", authored_by="firm",
        known_identifiers={"Foxfire": "CLIENT"})
    return ingest_document(store, caller, log, doc)


def test_survivor_rank_measured_beats_unmeasured():
    measured = {"kb_id": "kb_zzzzzzzzzz", "outcome": "shortlisted",
                "edit_survival": 0.4}
    fresh_winner_otherwise = {"kb_id": "kb_aaaaaaaaaa", "outcome": "won"}
    assert _survivor_is_candidate(fresh_winner_otherwise, measured) is False
    assert _survivor_is_candidate(measured, fresh_winner_otherwise) is True


def test_survivor_rank_higher_survival_wins_then_outcome_then_id():
    high = {"kb_id": "kb_zzzzzzzzzz", "outcome": "lost",
            "edit_survival": 0.9}
    low = {"kb_id": "kb_aaaaaaaaaa", "outcome": "won",
           "edit_survival": 0.2}
    assert _survivor_is_candidate(high, low) is True
    neither_a = {"kb_id": "kb_aaaaaaaaaa", "outcome": "won"}
    neither_b = {"kb_id": "kb_bbbbbbbbbb", "outcome": "won"}
    assert _survivor_is_candidate(neither_a, neither_b) is True  # kb_id last


def test_measured_near_dup_survives_a_better_outcome_candidate(tmp_path):
    """End to end: a shortlisted card that has EARNED a survival score is
    not displaced by a won-outcome near-duplicate — the measurement is
    the flywheel's memory and outranks provenance prestige."""
    store = KBStore(tmp_path / "kb")
    first = _ingest(store, "doc_a", BODY, "shortlisted", "run_0001")
    kept = first.cards_written[0]
    store.update_card_front(kept, edit_survival=0.75)

    second = _ingest(store, "doc_b", BODY_VARIANT, "won", "run_0002")
    assert second.cards_written == []
    assert store.card_exists(kept)
    merged = second.merged[0]
    assert merged["survivor"] == kept
    card, _ = store.read_card(kept)
    assert card["edit_survival"] == 0.75


def test_containment_override_transfers_the_measurement(tmp_path):
    """When the C8 containment rule outranks the survival tie-break — a
    container candidate absorbing a MEASURED fragment — the measurement
    transfers to the survivor: same content, same evidence, never
    discarded."""
    store = KBStore(tmp_path / "kb")
    first = _ingest(store, "doc_a", BODY, "shortlisted", "run_0001")
    fragment = first.cards_written[0]
    store.update_card_front(fragment, edit_survival=0.75)

    second = _ingest(store, "doc_b", BODY_EXTENDED, "won", "run_0002")
    assert len(second.cards_written) == 1
    survivor = second.cards_written[0]
    assert not store.card_exists(fragment)
    card, body = store.read_card(survivor)
    assert "Reconciliation runs wave by wave" in body
    assert card["edit_survival"] == 0.75


def test_retrieval_tie_break_prefers_measured_card(tmp_path):
    """Two cards with identical catalog text score identically; the one
    with observed survival returns first. Tie-breaking only — unequal
    scores are untouched (ranker tuning stays deferred, B41(1))."""
    store = KBStore(tmp_path / "kb")
    prov = {"source_pursuit": "pur_x", "source_client": "Foxfire",
            "date": "2026-08-01", "ingested_by": "test"}
    for kb_id in ("kb_aaaaaaaaa1", "kb_aaaaaaaaa2"):
        store.write_card(
            {"kb_id": kb_id, "layer": "corpus",
             "doc_kind": "section_exemplar",
             "title": "Data migration reconciliation",
             "summary": "Penny-level reconciliation approach.",
             "version": 1},
            "Body.", prov, {})
    store.update_card_front("kb_aaaaaaaaa2", edit_survival=0.9)
    log = RunLogger(store.root, "run_0001", "kb")
    result = card_search(store, "penny-level reconciliation", log=log,
                         stage="drafting", agent="section_drafter")
    assert [r.kb_id for r in result.results][:2] == \
        ["kb_aaaaaaaaa2", "kb_aaaaaaaaa1"]
    assert result.results[0].score == result.results[1].score