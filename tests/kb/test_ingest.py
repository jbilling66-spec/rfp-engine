"""Ingestion pipeline: the P2 acceptance clauses that live at ingest time.

10+ synthetic responses ingest to valid cards with a line-valid gapless run
log; re-ingest is idempotent (0 dups); buyer-authored sources are refused
(S4/T3); near-duplicates merge with a deterministic survivor whose
provenance carries every contributing client (D1); out-of-vocabulary facet
values are cleared and reported, never silently dropped (v1's silent-typo
lesson); a residual identifier variant blocks the write (E4).
"""

import json
from dataclasses import replace

from engine.contracts import check_runlog_payloads, validate
from engine.kb import KBStore, SourceDoc, ingest_document
from engine.llm import FakeCaller, TracedCaller
from engine.runlog import RunLogger, assert_seq_gapless, read_run

from tests.kb.fixtures.corpus import (
    PLANTED,
    SCRIPT,
    SOURCE_DOCS,
    WIRE,
    ingest_corpus,
)


def _run_log(store: KBStore, run_id: str = "run_0001") -> list[dict]:
    return read_run(store.root / "runs" / run_id / "run.jsonl")


def test_fixture_identifiers_actually_planted():
    """Self-check: PLANTED ground truth and the prose cannot drift apart."""
    for doc in SOURCE_DOCS:
        squashed = " ".join(doc.text.split())
        for identifier in PLANTED[doc.doc_id]:
            assert identifier in squashed, (
                f"{doc.doc_id}: planted identifier {identifier!r} not in doc text"
            )


def test_twelve_synthetic_responses_ingest_to_valid_cards(tmp_path):
    store, reports = ingest_corpus(tmp_path / "kb")
    assert len(reports) == 12
    assert all(r.status == "ingested" for r in reports)
    cards = store.list_cards()
    assert len(cards) >= 20
    for card in cards:
        record = store.restricted.read(card["kb_id"], actor="owner", purpose="audit")
        validate("kb_card", {**card, "provenance": {
            **record["sources"][0], "ingested_by": record["ingested_by"],
            "derived_from": record["derived_from"]}})
    records = _run_log(store)
    assert_seq_gapless(records)
    for record in records:
        validate("run_log", record)
        check_runlog_payloads(record)
    assert any(r["record_type"] == "kb_retrieval" for r in records)


def test_reingest_is_idempotent_zero_new_cards(tmp_path):
    store, _ = ingest_corpus(tmp_path / "kb")
    before_snapshot = store.snapshot()
    before_bytes = {
        p.name: p.read_bytes() for p in (store.root / "cards").glob("*.md")
    }
    store2, reports = ingest_corpus(tmp_path / "kb")
    assert all(r.cards_written == [] for r in reports)
    assert store2.snapshot() == before_snapshot
    assert {
        p.name: p.read_bytes() for p in (store2.root / "cards").glob("*.md")
    } == before_bytes


def test_ingest_is_byte_deterministic_across_directories(tmp_path):
    stores = [ingest_corpus(tmp_path / name)[0] for name in ("one", "two")]
    assert stores[0].snapshot() == stores[1].snapshot()
    prov = [
        {p.name: p.read_bytes() for p in (s.root / "restricted" / "provenance").glob("*.json")}
        for s in stores
    ]
    assert prov[0] == prov[1]


def test_buyer_authored_source_refused(tmp_path):
    store = KBStore(tmp_path / "kb")
    log = RunLogger(store.root, "run_0001", "kb")
    caller = TracedCaller(FakeCaller(SCRIPT), log)
    doc = SourceDoc(
        doc_id="resp_01", text="# DOC:resp_01\n## Q\nBuyer wrote this.",
        source_client="Northwind Regional Health", source_pursuit="pur_nrh",
        outcome="unknown", date="2026-01-01", authored_by="buyer",
    )
    report = ingest_document(store, caller, log, doc)
    assert report.status == "refused"
    assert store.list_cards() == []
    errors = [r for r in _run_log(store) if r["record_type"] == "error"]
    assert errors and errors[0]["error"]["code"] == "buyer_authored_source"


def test_near_duplicate_cross_client_won_variant_survives(tmp_path):
    store, reports = ingest_corpus(tmp_path / "kb")
    merges = {m["absorbed"]: m for r in reports for m in r.merged}
    training = [
        c for c in store.list_cards()
        if "training" in c.get("section_types", []) and c["doc_kind"] == "section_exemplar"
        and "super-user" in store.read_card(c["kb_id"])[1]
    ]
    assert len(training) == 1
    survivor = training[0]
    assert survivor["outcome"] == "won"
    assert merges, "expected at least one dedup merge"


def test_merged_card_carries_both_source_clients(tmp_path):
    store, _ = ingest_corpus(tmp_path / "kb")
    training = [
        c for c in store.list_cards()
        if "training" in c.get("section_types", [])
        and "super-user" in store.read_card(c["kb_id"])[1]
    ][0]
    record = store.restricted.read(training["kb_id"], actor="owner", purpose="audit")
    clients = {s["source_client"] for s in record["sources"]}
    assert {"Cascade Valley Medical Center", "Harborlight Insurance Group"} <= clients


def test_within_client_near_duplicate_merges_to_one_card(tmp_path):
    store, _ = ingest_corpus(tmp_path / "kb")
    replay_testing = [
        c for c in store.list_cards()
        if "thirty days of production message" in store.read_card(c["kb_id"])[1]
    ]
    assert len(replay_testing) == 1


def test_out_of_vocab_facets_cleared_not_dropped(tmp_path):
    store = KBStore(tmp_path / "kb")
    log = RunLogger(store.root, "run_0001", "kb")
    wire = json.loads(WIRE["resp_01"])
    wire["chunk_annotations"][0]["section_types"] = ["Methodology Overview"]
    caller = TracedCaller(FakeCaller({"ingestion_agent": json.dumps(wire)}), log)
    report = ingest_document(store, caller, log, SOURCE_DOCS[0])
    assert report.status == "ingested"
    assert {"where": "chunk 0", "facet": "section_types",
            "value": "Methodology Overview"} in report.cleared_facets
    first_card = store.read_card(report.cards_written[0])[0]
    assert first_card["section_types"] == []


def test_residual_identifier_variant_blocks_ingestion(tmp_path):
    """v2 framing of the P2 case: the model no longer supplies text, so
    the residual variant lives in the DOCUMENT — a possessive the
    longest-first substitution misses ("Meridian's" after "Meridian
    Health Partners" is replaced). The scan gate must catch it, block
    every write, and leave no L1 model behind."""
    store = KBStore(tmp_path / "kb")
    log = RunLogger(store.root, "run_0001", "kb")
    caller = TracedCaller(FakeCaller({"ingestion_agent": WIRE["resp_01"]}), log)
    doc = replace(SOURCE_DOCS[0],
                  text=SOURCE_DOCS[0].text
                  + "\nMeridian's team praised the cutover.")
    report = ingest_document(store, caller, log, doc)
    assert report.status == "blocked"
    assert report.route_to == "owner"
    assert store.list_cards() == []
    assert not (store.root / "canonical").exists() or \
        list((store.root / "canonical").glob("*.json")) == []
    validations = [r for r in _run_log(store) if r["record_type"] == "validation"]
    assert validations[-1]["validation"] == {"check": "anonymization",
                                            "result": "block"}
