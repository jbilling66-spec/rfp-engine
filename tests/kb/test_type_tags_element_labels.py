"""C13 — the ROADMAP P12 clause by name: element labels absent from
type_tags. The spec's §A5 sentence (EXTRACTION_AND_SCALE_SPEC): docling's
element labels are NEVER written into type_tags — a table is not a kind of
knowledge; the enums never merge. The whitelist has enforced this since
K3; these tests make it a named, spec-cited property in both directions."""

import json

from engine.extraction.model import DOCLING_ELEMENT_LABELS
from engine.kb import KBStore, ingest_document
from engine.kb.ingest import TYPE_TAGS
from engine.llm import FakeCaller, TracedCaller
from engine.runlog import RunLogger
from tests.kb.fixtures.corpus import SOURCE_DOCS, WIRE


def test_vocabularies_are_disjoint():
    # Direction 1: the enums can never merge silently — if a docling
    # label is ever added to TYPE_TAGS (or vice versa) this reddens.
    assert TYPE_TAGS & DOCLING_ELEMENT_LABELS == frozenset()


def test_wire_proposing_element_labels_is_cleared_and_reported(tmp_path):
    # Direction 2: a model wire that proposes container vocabulary as
    # knowledge taxonomy gets cleared by the K3 whitelist and REPORTED —
    # never silently dropped, never silently kept.
    doc = SOURCE_DOCS[0]
    honest = json.loads(WIRE[doc.doc_id])
    for annotation in honest["chunk_annotations"]:
        annotation["type_tags"] = ["table", "section_header", "figure"]
    poisoned = json.dumps(honest)

    store = KBStore(tmp_path / "kb")
    log = RunLogger(store.root, "run_0001", "kb")
    caller = TracedCaller(FakeCaller({"ingestion_agent": poisoned}), log)
    report = ingest_document(store, caller, log, doc)

    assert report.status == "ingested"
    cleared_values = {
        entry["value"] for entry in report.cleared_facets
        if entry["facet"] == "type_tags"
    }
    assert {"table", "section_header", "figure"} <= cleared_values
    for kb_id in report.cards_written:
        card, _body = store.read_card(kb_id)
        assert not set(card.get("type_tags", [])) & DOCLING_ELEMENT_LABELS
