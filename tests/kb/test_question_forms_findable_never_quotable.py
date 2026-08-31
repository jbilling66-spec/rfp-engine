"""P17/C5 — the ROADMAP clause by name: question-forms generated at
ingest are FINDABLE but NEVER QUOTABLE (the X10 generated_description
treatment applied to retrieval aids, B65 enrichment step 1).

The structural guard: forms live in card FRONTMATTER only. The scored
catalog text joins them (findable); the body — the only thing
targeted_open returns and the only content wrap_kb_card puts in a
drafting frame — never contains them (never quotable). A distinctive
token planted in a form proves both directions, and the questioner's
output rides the same anonymization belt as every other model text.
Under questioner=None (production, pre-A1) no field is written — the
committed corpus stays byte-identical and the mapper pins hold (B75§4a).
"""

import json

from engine.kb import KBStore, SourceDoc, card_search, ingest_document
from engine.kb.canonical import Element
from engine.kb.retrieve import targeted_open
from engine.llm import FakeCaller, TracedCaller
from engine.llm.frames import wrap_kb_card
from engine.runlog import RunLogger

TOKEN = "zorbification"  # appears NOWHERE except the planted form


def _wire() -> str:
    return json.dumps({
        "chunk_annotations": [
            {"chunk": 0, "summary": "Cutover rehearsal exemplar.",
             "section_types": [], "type_tags": []}],
        "qa_pairs": [], "identifiers": [],
        "client_descriptor": "a synthetic firm",
    })


DOC = ("Cutover Rehearsals\n\nNine waves completed for Foxfire with zero "
       "rollbacks across the program.")


def _elements():
    return [
        Element(kind="heading", text="Cutover Rehearsals", level=2),
        Element(kind="paragraph",
                text="Nine waves completed for Foxfire with zero "
                     "rollbacks across the program."),
    ]


def _ingest(tmp_path, questioner=None):
    store = KBStore(tmp_path / "kb")
    log = RunLogger(store.root, "run_0001", "kb")
    caller = TracedCaller(FakeCaller({"ingestion_agent": _wire()}), log)
    doc = SourceDoc(doc_id="qf_doc", text=DOC, source_client="Foxfire",
                    source_pursuit="pur_qf", outcome="won",
                    date="2026-08-01", authored_by="firm",
                    known_identifiers={"Foxfire": "CLIENT"},
                    elements=_elements())
    report = ingest_document(store, caller, log, doc, questioner=questioner)
    assert report.status == "ingested"
    return store, log, report


def _questioner(model):
    return {i: [f"how does {TOKEN} of legacy waves get rehearsed?",
                "what did Foxfire rehearse before cutover?"]
            for i in range(len(model.chunks))}


def test_question_forms_findable_never_quotable(tmp_path):
    """The named test: the planted token FINDS the card and can never
    leave the catalog — absent from the opened body, absent from the
    drafting frame."""
    store, log, report = _ingest(tmp_path, questioner=_questioner)
    result = card_search(store, f"explain {TOKEN} for this program",
                         log=log, stage="ingestion", agent="kb_mapper")
    assert result.results, "the form must make the card findable"
    kb_id = result.results[0].kb_id
    assert kb_id in report.cards_written

    card, body = store.read_card(kb_id)
    assert any(TOKEN in q for q in card["question_forms"])
    assert TOKEN not in body, "the quotable surface never holds the form"
    opened = targeted_open(store, kb_id, log=log, stage="ingestion",
                           agent="kb_mapper", query="plan:sec-01")
    assert TOKEN not in opened
    frame = wrap_kb_card(kb_id, card.get("title", ""), opened)
    assert TOKEN not in frame, "no drafting frame ever carries a form"


def test_question_forms_ride_the_anonymization_belt(tmp_path):
    store, log, report = _ingest(tmp_path, questioner=_questioner)
    for kb_id in report.cards_written:
        card, _ = store.read_card(kb_id)
        for form in card.get("question_forms", []):
            assert "Foxfire" not in form, \
                "a model-generated form is anonymized like any model text"


def test_no_questioner_writes_no_field(tmp_path):
    """Writers-omit: production passes None pre-A1, so the committed
    corpus stays unenriched and its catalog text byte-stable."""
    store, _log, report = _ingest(tmp_path, questioner=None)
    for kb_id in report.cards_written:
        card, _ = store.read_card(kb_id)
        assert "question_forms" not in card
