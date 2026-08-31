"""C19 (P13) — the ROADMAP clause's second half, by name: no size limit
enforced anywhere AND the chunk-size distribution observable (R4/R5).
The no-cap half lives at C5 (test_chunk.py); this file proves the
distribution is derivable from the store and honest about outliers."""

import json

from engine.kb import KBStore, SourceDoc, ingest_document
from engine.kb.curation import chunk_size_distribution
from engine.llm import FakeCaller, TracedCaller
from engine.runlog import RunLogger

from tests.kb.fixtures.corpus import ingest_corpus


def test_distribution_observable_from_the_committed_corpus(tmp_path):
    store, reports = ingest_corpus(tmp_path / "kb")
    dist = chunk_size_distribution(store)
    assert dist["n"] > 20
    assert dist["min"] <= dist["p50"] <= dist["p95"] <= dist["max"]
    assert dist["total_chars"] > 0
    # The report carries the raw sizes per document (R5's surface).
    assert all(r.chunk_sizes for r in reports)


def test_giant_chunk_is_visible_not_clipped(tmp_path):
    """An outlier is an extraction FINDING — it must show up in the
    distribution at its true size, never truncated by any layer."""
    store = KBStore(tmp_path / "kb")
    log = RunLogger(store.root, "run_0001", "kb")
    giant_body = "\n".join(
        f"Requirement {i}: the vendor shall comply fully." for i in range(400))
    wire = json.dumps({"chunk_annotations": [
        {"chunk": 0, "summary": "A pathologically merged section.",
         "section_types": [], "type_tags": []}],
        "qa_pairs": [], "identifiers": [],
        "client_descriptor": "an org"})
    caller = TracedCaller(FakeCaller({"ingestion_agent": wire}), log)
    doc = SourceDoc(doc_id="giant", text=f"# DOC:giant\n\n## Everything\n\n"
                    f"{giant_body}\n",
                    source_client="Foxfire", source_pursuit="pur_g",
                    outcome="won", date="2026-08-01", authored_by="firm",
                    known_identifiers={"Foxfire": "CLIENT"})
    report = ingest_document(store, caller, log, doc)
    assert report.status == "ingested"
    expected = len(giant_body)
    assert report.chunk_sizes == [expected]
    dist = chunk_size_distribution(store)
    assert dist["max"] == expected
    card = store.read_card(report.cards_written[0])[0]
    assert card["chunk_span"]["chars"] == expected


def test_empty_store_reports_zero_not_error(tmp_path):
    assert chunk_size_distribution(KBStore(tmp_path / "kb")) == {"n": 0}