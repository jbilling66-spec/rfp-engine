"""C11 (P13) — heading-path descent (WP13 R9): parent/siblings/children
via the canonical model's backrefs, one file read, document order,
recorded on the trace. Pre-WP13 cards descend to a recorded empty
result, never an error (R11)."""

import json

import pytest

from engine.contracts import ContractError
from engine.kb import KBStore, SourceDoc, ingest_document
from engine.kb.retrieve import descend
from engine.llm import FakeCaller, TracedCaller
from engine.runlog import RunLogger, read_run

DOC = """# DOC:nav_doc

## Approach

Discovery is fixed scope with weekly steering checkpoints throughout.

### Method

Waves are cut over with rollback rehearsals before every go decision.

### Tools

The migration workbench validates mappings before any load runs.

## Team

Five consultants staff the engagement with named backfill coverage.
"""


def _wire(n: int) -> str:
    return json.dumps({
        "chunk_annotations": [
            {"chunk": i, "summary": f"Summary {i}.", "section_types": [],
             "type_tags": []} for i in range(n)],
        "qa_pairs": [], "identifiers": [],
        "client_descriptor": "a synthetic firm",
    })


@pytest.fixture()
def seeded(tmp_path):
    store = KBStore(tmp_path / "kb")
    log = RunLogger(store.root, "run_0001", "kb")
    caller = TracedCaller(FakeCaller({"ingestion_agent": _wire(4)}), log)
    doc = SourceDoc(doc_id="nav_doc", text=DOC, source_client="Foxfire",
                    source_pursuit="pur_nav", outcome="won",
                    date="2026-08-01", authored_by="firm",
                    known_identifiers={"Foxfire": "CLIENT"})
    report = ingest_document(store, caller, log, doc)
    assert report.status == "ingested" and len(report.cards_written) == 4
    by_title = {store.read_card(k)[0]["title"]: k
                for k in report.cards_written}
    return store, by_title


def _log(store, run):
    return RunLogger(store.root, run, "kb")


def test_children_in_document_order(seeded):
    store, ids = seeded
    result = descend(store, ids["Approach"], "children",
                     log=_log(store, "run_0002"), stage="drafting",
                     agent="section_drafter")
    assert [r.card["title"] for r in result.results] == ["Method", "Tools"]


def test_parent(seeded):
    store, ids = seeded
    result = descend(store, ids["Method"], "parent",
                     log=_log(store, "run_0003"), stage="drafting",
                     agent="section_drafter")
    assert [r.card["title"] for r in result.results] == ["Approach"]


def test_siblings(seeded):
    store, ids = seeded
    result = descend(store, ids["Method"], "siblings",
                     log=_log(store, "run_0004"), stage="drafting",
                     agent="section_drafter")
    assert [r.card["title"] for r in result.results] == ["Tools"]


def test_top_level_siblings_and_absent_parent(seeded):
    store, ids = seeded
    siblings = descend(store, ids["Approach"], "siblings",
                       log=_log(store, "run_0005"), stage="drafting",
                       agent="section_drafter")
    assert [r.card["title"] for r in siblings.results] == ["Team"]
    parent = descend(store, ids["Approach"], "parent",
                     log=_log(store, "run_0006"), stage="drafting",
                     agent="section_drafter")
    assert parent.results == []


def test_restricted_anchor_descends_to_recorded_empty(seeded):
    """M-28 (P26b-2): a use_restriction card is not a navigation handle
    either — its siblings used to come back, leaking the restricted
    card's position in the document. Recorded-empty, the anchor
    withheld on the trace, exactly as search records it."""
    from engine.runlog import read_run

    store, ids = seeded
    store.update_card_front(ids["Method"], use_restriction=True)
    result = descend(store, ids["Method"], "siblings",
                     log=_log(store, "run_0027"), stage="drafting",
                     agent="section_drafter")
    assert result.results == []
    assert result.excluded == [{"kb_id": ids["Method"],
                                "reason": "use_restriction"}]
    records = read_run(store.root / "runs" / "run_0027" / "run.jsonl")
    line = [r for r in records if r["record_type"] == "kb_retrieval"][-1]
    assert line["kb"]["step"] == "path_descend"
    assert line["kb"]["excluded"] == [ids["Method"]]
    assert line["kb"]["empty_result"] is True


def test_use_restriction_honored_and_recorded(seeded):
    store, ids = seeded
    store.update_card_front(ids["Tools"], use_restriction=True)
    result = descend(store, ids["Method"], "siblings",
                     log=_log(store, "run_0007"), stage="drafting",
                     agent="section_drafter")
    assert result.results == []
    assert result.excluded == [{"kb_id": ids["Tools"],
                                "reason": "use_restriction"}]


def test_pre_wp13_card_descends_to_recorded_empty(seeded):
    """R11: a card written before the canonical model exists works
    without the second move — empty result on the trace, never an
    error."""
    store, _ids = seeded
    old_shape = {
        "kb_id": "kb_prewp13doc", "layer": "corpus",
        "doc_kind": "section_exemplar", "title": "Legacy card",
        "summary": "Written before WP13.", "version": 1,
    }
    store.write_card(old_shape, "Legacy body.",
                     {"source_pursuit": "pur_old", "source_client": "Foxfire",
                      "date": "2025-01-01", "ingested_by": "test"}, {})
    log = _log(store, "run_0008")
    result = descend(store, "kb_prewp13doc", "children", log=log,
                     stage="drafting", agent="section_drafter")
    assert result.results == [] and result.excluded == []
    line = [r for r in read_run(store.root / "runs" / "run_0008" / "run.jsonl")
            if r["record_type"] == "kb_retrieval"][-1]
    assert line["kb"]["step"] == "path_descend"
    assert line["kb"]["empty_result"] is True


def test_trace_line_carries_anchor_path_and_relation(seeded):
    store, ids = seeded
    log = _log(store, "run_0009")
    descend(store, ids["Method"], "siblings", log=log, stage="drafting",
            agent="section_drafter")
    line = [r for r in read_run(store.root / "runs" / "run_0009" / "run.jsonl")
            if r["record_type"] == "kb_retrieval"][-1]
    kb = line["kb"]
    assert kb["query"] == f"descend:{ids['Method']}"
    assert kb["relation"] == "siblings"
    assert kb["path"] == ["Approach", "Method"]
    assert "catalog_size" not in kb, "descent never scans the catalog"


def test_unknown_relation_refused(seeded):
    store, ids = seeded
    with pytest.raises(ContractError, match="unknown relation"):
        descend(store, ids["Method"], "cousins",
                log=_log(store, "run_0010"), stage="drafting",
                agent="section_drafter")
