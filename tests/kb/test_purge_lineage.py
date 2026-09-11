"""P1-52 (P29b b6): `purge_client` walked restricted provenance only, so
the claim-promotion `new_card` proposal derived from a purged chunk card
sat `proposed` in the steward inbox; an ordinary accept re-minted the
purged client's placeholdered material with no `source_client` and a
`derived_from` pointing at nothing, and a second purge reported CLEAN —
the A1 purge guarantee breakable by the steward loop. Now the closure
follows `derived_from` INTO the proposal store (voided, logged), an
accept over a missing target refuses, and the sweep names any live
proposal still citing a purged card."""

import json

import pytest

from engine.flywheel.proposals import ProposalStore
from engine.kb import KBStore, SourceDoc, ingest_document, purge_client
from engine.kb.curation import CurationRefused, merge_batch
from engine.kb.purge import post_purge_sweep
from engine.llm import FakeCaller, TracedCaller
from engine.runlog import RunLogger
from tests.kb.fixtures.corpus import REVIEWER_NONE

CLIENT = "Larkspur Freight Cooperative"
AT = "2026-09-11T09:00:00Z"
FILLS = {"owner": "steward", "verified_date": "2026-09-11"}
DOC = """# DOC:lineage_doc

## Past Performance

Across the program we completed twelve depot consolidations, and the
combined engagement value reached $3,150,000 without a missed cutover.
"""
CLAIM = ("We completed twelve depot consolidations for Larkspur Freight "
         "Cooperative at a combined fee of $3,150,000.")


def _wire() -> str:
    return json.dumps({
        "chunk_annotations": [
            {"chunk": 0, "summary": "Past performance exemplar.",
             "section_types": ["past_performance"],
             "type_tags": ["proof_case_study"],
             "claim_candidates": [CLAIM]}],
        "qa_pairs": [],
        "identifiers": [{"value": CLIENT, "type": "CLIENT"},
                        {"value": "$3,150,000", "type": "FEE"}],
        "client_descriptor": "a regional freight cooperative",
    })


def _ingest(store, run="run_0001"):
    log = RunLogger(store.root, run, "kb")
    caller = TracedCaller(
        FakeCaller({"ingestion_agent": _wire(), **REVIEWER_NONE}), log)
    doc = SourceDoc(doc_id="lineage_doc", text=DOC, source_client=CLIENT,
                    source_pursuit="pur_lineage", outcome="won",
                    date="2026-08-01", authored_by="firm",
                    known_identifiers={CLIENT: "CLIENT"})
    return ingest_document(store, caller, log, doc)


def _log_lines(store):
    path = store.root / "curation-log.jsonl"
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()]


def test_the_purge_voids_the_proposal_derived_from_a_purged_card(tmp_path):
    store = KBStore(tmp_path / "kb")
    report = _ingest(store)
    assert report.status == "ingested" and len(report.proposals) == 1
    pid = report.proposals[0]
    proposals = ProposalStore(store.root)
    assert proposals.read(pid)["status"] == "proposed"

    purge = purge_client(store, CLIENT, actor="owner", at=AT)
    assert purge.purged and purge.swept_clean, purge.sweep_findings
    record = proposals.read(pid)
    assert record["status"] == "voided"
    assert record["decided"]["decision"] == "voided"
    assert record["decided"]["by"] == "purge:owner"
    assert CLIENT not in json.dumps(record)  # the cascade never names it
    assert purge.accounting["voided_proposals"] == [pid]
    line = _log_lines(store)[-1]
    assert line["voided"] == [pid] and line["by"] == "purge:owner"
    assert "purge cascade" in line["reason"] and CLIENT not in json.dumps(line)

    # the ordinary steward loop can no longer re-mint the material
    with pytest.raises(CurationRefused, match="already voided"):
        merge_batch(store, [pid], operator="steward", at=AT,
                    fills={pid: FILLS})
    assert store.list_cards() == []

    # a re-ingest of the same bytes meets the voided record (ids are
    # content-deterministic; open() is a no-op re-propose) — it does not
    # silently re-open the purged material's route into the inbox
    again = _ingest(store, run="run_0002")
    assert again.proposals == [pid]
    assert proposals.read(pid)["status"] == "voided"

    # a second purge has nothing left to void and stays clean
    purge2 = purge_client(store, CLIENT, actor="owner", at=AT)
    assert purge2.accounting["voided_proposals"] == []
    assert purge2.swept_clean, purge2.sweep_findings


def _open_derived(store, targets, pid_suffix="a"):
    return ProposalStore(store.root).open(
        source={"door": "ingestion", "pursuit_id": f"pur_{pid_suffix}"},
        target="fact_sheet", kind="new_card", at=AT, diff={
            "title": {"after": "Depot consolidations delivered on time"},
            "body": {"after": "We delivered [CLIENT]'s twelve depot "
                              "consolidations on time."},
            "layer": {"after": "fact_sheet"},
            "grain": {"after": "atom"},
            "content_origin": {"after": "source_text"},
            "derived_from": {"after": targets}})


def test_an_accept_over_a_missing_derived_from_target_is_refused(tmp_path):
    store = KBStore(tmp_path / "kb")
    proposal = _open_derived(store, ["kb_gone00001"])
    pid = proposal["proposal_id"]
    with pytest.raises(CurationRefused, match="do not exist"):
        merge_batch(store, [pid], operator="steward", at=AT,
                    fills={pid: FILLS})
    assert store.list_cards() == []
    assert ProposalStore(store.root).read(pid)["status"] == "proposed"


def test_the_sweep_names_a_live_proposal_citing_a_purged_card(tmp_path):
    store = KBStore(tmp_path / "kb")
    live = _open_derived(store, ["kb_purged0001"], "live")
    decided = _open_derived(store, ["kb_purged0001"], "done")
    ProposalStore(store.root).void(decided["proposal_id"], by="t", at=AT,
                                   note="already voided")
    findings = post_purge_sweep(store, [], ["kb_purged0001"])
    assert findings == [
        f"proposal:{live['proposal_id']}: cites purged card kb_purged0001"]
