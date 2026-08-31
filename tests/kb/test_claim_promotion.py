"""C15 (P13) — the owner's promotion call (B59): claim candidates become
fact-sheet NEW-CARD PROPOSALS at ingest; nothing becomes a verified
fact until a steward supplies owner + verified_date at acceptance."""

import json

import pytest

from engine.flywheel.proposals import ProposalStore
from engine.kb import KBStore, SourceDoc, ingest_document
from engine.kb.curation import CurationRefused, merge_batch
from engine.validation.claims import fact_catalog
from engine.llm import FakeCaller, TracedCaller
from engine.runlog import RunLogger

CLIENT = "Foxfire Analytics"
CLAIM = ("We completed forty ERP go-lives for Foxfire Analytics at a "
         "combined fee of $9,400,000.")

DOC = """# DOC:claim_doc

## Past Performance

Across the program we completed forty ERP go-lives, and the combined
engagement value reached $9,400,000 without a missed cutover date.
"""


def _wire() -> str:
    return json.dumps({
        "chunk_annotations": [
            {"chunk": 0, "summary": "Past performance exemplar.",
             "section_types": ["past_performance"],
             "type_tags": ["proof_case_study"],
             "claim_candidates": [CLAIM]}],
        "qa_pairs": [],
        "identifiers": [{"value": CLIENT, "type": "CLIENT"},
                        {"value": "$9,400,000", "type": "FEE"}],
        "client_descriptor": "a mid-size analytics firm",
    })


def _ingest(store, run="run_0001"):
    log = RunLogger(store.root, run, "kb")
    caller = TracedCaller(FakeCaller({"ingestion_agent": _wire()}), log)
    doc = SourceDoc(doc_id="claim_doc", text=DOC, source_client=CLIENT,
                    source_pursuit="pur_claim_2026", outcome="won",
                    date="2026-08-01", authored_by="firm",
                    known_identifiers={CLIENT: "CLIENT"})
    return ingest_document(store, caller, log, doc)


def test_claim_candidate_becomes_an_anonymized_proposal(tmp_path):
    store = KBStore(tmp_path / "kb")
    report = _ingest(store)
    assert report.status == "ingested"
    assert len(report.proposals) == 1
    proposal = ProposalStore(store.root).read(report.proposals[0])
    assert proposal["status"] == "proposed"
    assert proposal["kind"] == "new_card"
    assert proposal["target"] == "fact_sheet"
    assert proposal["source"]["door"] == "ingestion"
    body = proposal["diff"]["body"]["after"]
    assert "[CLIENT]" in body and "[FEE]" in body
    assert CLIENT not in body and "$9,400,000" not in body
    # The purge link: derived_from names the source chunk card.
    assert proposal["diff"]["derived_from"]["after"] == \
        [report.cards_written[0]]


def test_nothing_becomes_a_fact_card_without_a_steward(tmp_path):
    store = KBStore(tmp_path / "kb")
    _ingest(store)
    assert fact_catalog(store) == []


def test_reingest_reproposes_as_a_noop(tmp_path):
    store = KBStore(tmp_path / "kb")
    first = _ingest(store, "run_0001")
    second = _ingest(store, "run_0002")
    assert second.proposals == first.proposals
    assert len(ProposalStore(store.root).list()) == 1


def test_blocked_ingest_mints_no_proposal(tmp_path):
    """The scan gate covers proposal text: a residual identifier variant
    anywhere blocks EVERYTHING, proposals included."""
    store = KBStore(tmp_path / "kb")
    log = RunLogger(store.root, "run_0001", "kb")
    caller = TracedCaller(FakeCaller({"ingestion_agent": _wire()}), log)
    doc = SourceDoc(doc_id="claim_doc",
                    text=DOC + "\nFoxfire's team praised the cutover.\n",
                    source_client=CLIENT, source_pursuit="pur_claim_2026",
                    outcome="won", date="2026-08-01", authored_by="firm",
                    known_identifiers={CLIENT: "CLIENT"})
    report = ingest_document(store, caller, log, doc)
    assert report.status == "blocked"
    assert report.proposals == []
    assert ProposalStore(store.root).list() == []


def test_acceptance_refused_without_owner_and_verified_date(tmp_path):
    store = KBStore(tmp_path / "kb")
    report = _ingest(store)
    with pytest.raises(CurationRefused, match="owner and verified_date"):
        merge_batch(store, report.proposals, operator="owner",
                    at="2026-08-24T00:00:00Z")
    assert fact_catalog(store) == []
    # The refusal left the proposal undecided — the steward can retry.
    assert ProposalStore(store.root).read(
        report.proposals[0])["status"] == "proposed"


def test_steward_acceptance_mints_the_fact_atom(tmp_path):
    store = KBStore(tmp_path / "kb")
    report = _ingest(store)
    pid = report.proposals[0]
    merge_batch(store, [pid], operator="owner", at="2026-08-24T00:00:00Z",
                fills={pid: {"owner": "owner",
                             "verified_date": "2026-08-24"}})
    facts = fact_catalog(store)
    assert len(facts) == 1
    fact = facts[0]
    assert fact["layer"] == "fact_sheet"
    assert fact["grain"] == "atom"
    assert fact["doc_kind"] == "fact"
    assert fact["content_origin"] == "source_text"
    assert fact["owner"] == "owner"
    _card, body = store.read_card(fact["kb_id"])
    assert "[FEE]" in body
    # Purge linkage survived into the restricted record.
    prov = json.loads(
        (store.root / "restricted" / "provenance"
         / f"{fact['kb_id']}.json").read_text())
    assert prov["derived_from"] == [report.cards_written[0]]
    assert ProposalStore(store.root).read(pid)["status"] == "accepted"