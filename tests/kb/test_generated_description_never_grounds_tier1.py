"""C13 (P13) — the ROADMAP clause by name: a generated description can
never ground a Tier-1 claim. Three interlocking guards, proven in order
of depth (B59's structural lever; claim_tier_max is deliberately NOT
the mechanism — zero readers, wrong signal, X10 deviation recorded):

  1. the schema refuses a generated-description fact card outright;
  2. a smuggled one (hand-edited store, bypassing every validated
     write) is invisible to fact_catalog — the belt;
  3. a Tier-1 claim citing it therefore audits as no-referent, which
     BLOCKS packaging.

Plus the hazard guard: none of this touches the seven rostered scoring
functions whose semantic hashes gate the live-funded poison and
claim-extraction baselines.
"""

import json

import pytest

from engine.contracts import ContractError, validate
from engine.kb import KBStore, SourceDoc, ingest_document
from engine.kb.canonical import Element
from engine.validation.audit import audit_claim
from engine.validation.claims import fact_catalog
from engine.llm import FakeCaller, TracedCaller
from engine.runlog import RunLogger


def _smuggle_generated_description_fact_card(store: KBStore) -> str:
    """Write a card file DIRECTLY, bypassing store.write_card and its
    schema validation — the hand-edited-store case the belt exists for."""
    kb_id = "kb_smuggled01"
    (store.cards_dir / f"{kb_id}.md").write_text(
        "---\n"
        "content_origin: generated_description\n"
        f"kb_id: {kb_id}\n"
        "layer: fact_sheet\n"
        "owner: nobody\n"
        "summary: A vision model says the chart shows 40 go-lives.\n"
        "title: Chart caption\n"
        "verified_date: '2026-08-01'\n"
        "---\n"
        "The chart shows forty successful go-lives.\n",
        encoding="utf-8")
    return kb_id


def test_generated_description_can_never_ground_a_tier1_claim(tmp_path):
    """The named test, all three guards in one arc."""
    # Guard 1: the schema refuses the combination at every validated write.
    with pytest.raises(ContractError):
        validate("kb_card", {
            "kb_id": "kb_x", "layer": "fact_sheet", "summary": "s",
            "owner": "o", "verified_date": "2026-08-01",
            "content_origin": "generated_description"})

    # Guard 2: a smuggled card is invisible to the auditor's catalog.
    store = KBStore(tmp_path / "kb")
    smuggled = _smuggle_generated_description_fact_card(store)
    assert any(c["kb_id"] == smuggled for c in store.list_cards()), \
        "the smuggle must be real for the belt to be tested"
    catalog = fact_catalog(store)
    assert smuggled not in {c["kb_id"] for c in catalog}

    # Guard 3: a Tier-1 claim citing it audits as no-referent -> BLOCK.
    facts_by_id = {c["kb_id"]: c for c in catalog}
    claim = {"claim_id": "c1", "tier": 1, "text": "Forty go-lives.",
             "fact_sheet_ref": smuggled}
    audited = audit_claim(claim, verdict=None, reasons=[],
                          fact_card=facts_by_id.get(claim["fact_sheet_ref"]),
                          at="2026-08-24")
    assert audited["disposition"] == "block"
    assert audited["status"] == "unverifiable"


def test_scoring_roster_membership_unchanged():
    """The baseline hazard guard: the lever lives in the schema and
    fact_catalog, neither of which is rostered — so the live-funded
    poison/claim_extraction baselines cannot have been staled by C13."""
    from engine.evals.cases import _SCORING_ROSTER

    assert _SCORING_ROSTER == (
        ("engine.validation.claims", "parse_extraction_wire"),
        ("engine.validation.claims", "build_extraction_prompt"),
        ("engine.validation.audit", "build_verify_prompt"),
        ("engine.validation.audit", "parse_verdict_wire"),
        ("engine.validation.audit", "audit_claim"),
        ("engine.validation.validate", "run_claim_audit"),
        ("engine.evals.cases", "miss_cause"),
    )
    assert ("engine.validation.claims", "fact_catalog") not in _SCORING_ROSTER


# ------------------------------------------- the ingest side (figure cards)

DOC = """# DOC:fig_doc

## Delivery Metrics

Nine waves completed with zero rollbacks across the program.
"""


def _wire() -> str:
    return json.dumps({
        "chunk_annotations": [
            {"chunk": 0, "summary": "Delivery metrics exemplar.",
             "section_types": [], "type_tags": []}],
        "qa_pairs": [], "identifiers": [],
        "client_descriptor": "a synthetic firm",
    })


def _elements(figure_class: str):
    return [
        Element(kind="heading", text="Delivery Metrics", level=2),
        Element(kind="paragraph",
                text="Nine waves completed with zero rollbacks across "
                     "the program."),
        Element(kind="figure", text="", figure_class=figure_class),
    ]


def _ingest(tmp_path, figure_class, describer=None):
    store = KBStore(tmp_path / "kb")
    log = RunLogger(store.root, "run_0001", "kb")
    caller = TracedCaller(FakeCaller({"ingestion_agent": _wire()}), log)
    doc = SourceDoc(doc_id="fig_doc", text=DOC, source_client="Foxfire",
                    source_pursuit="pur_fig", outcome="won",
                    date="2026-08-01", authored_by="firm",
                    known_identifiers={"Foxfire": "CLIENT"},
                    elements=_elements(figure_class))
    return store, ingest_document(store, caller, log, doc,
                                  describer=describer)


def test_described_figure_mints_a_labeled_card(tmp_path):
    def describer(model):
        figure_chunks = {
            i for i, c in enumerate(model.chunks)
            if any(e.kind == "figure"
                   for e in model.elements[c.elements[0]:c.elements[1]])}
        return {i: "A bar chart of go-live counts by wave."
                for i in figure_chunks}

    store, report = _ingest(tmp_path, "chart", describer)
    assert report.status == "ingested"
    figure_cards = [store.read_card(k)[0] for k in report.cards_written
                    if store.read_card(k)[0].get("figure_class")]
    assert len(figure_cards) == 1
    card = figure_cards[0]
    assert card["content_origin"] == "generated_description"
    assert card["figure_class"] == "chart"
    assert card["layer"] == "corpus"
    assert "claim_tier_max" not in card  # the X10 deviation, by design


def test_undescribed_figure_mints_nothing(tmp_path):
    store, report = _ingest(tmp_path, "chart", describer=None)
    assert report.status == "ingested"
    assert all(not store.read_card(k)[0].get("figure_class")
               for k in report.cards_written)


def test_logo_is_removed_never_described_and_flags(tmp_path):
    describer_called_for = []

    def describer(model):
        figure_chunks = {
            i for i, c in enumerate(model.chunks)
            if any(e.kind == "figure"
                   for e in model.elements[c.elements[0]:c.elements[1]])}
        describer_called_for.extend(figure_chunks)
        return {i: "A company logo." for i in figure_chunks}

    store, report = _ingest(tmp_path, "logo", describer)
    assert report.status == "ingested"
    assert report.media_flagged is True
    assert all(not store.read_card(k)[0].get("figure_class")
               for k in report.cards_written)
    assert all(store.read_card(k)[0].get("content_origin") !=
               "generated_description" for k in report.cards_written)