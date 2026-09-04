"""P26c (P1-43): every proposal names its home BEFORE the decision —
`home_of` is what the inbox shows, what pass 1 of merge_batch refuses on,
and what pass 2 dispatches on. A note kind's home is the accepted record
itself: accepting it changes no card and IS the note the drafter reads."""

import pytest

from engine.flywheel.proposals import ProposalStore
from engine.kb.curation import (NOTE_KINDS, CurationRefused, home_of,
                                merge_batch)
from engine.kb.store import KBStore

PROV = {"source_pursuit": "pur_x", "source_client": "Fixture County",
        "date": "2026-01-01", "ingested_by": "ingestion_agent"}
AT = "2026-09-04T10:00:00Z"
CARD = "kb_home000001"


@pytest.fixture
def store(tmp_path):
    store = KBStore(tmp_path / "kb")
    store.write_card(
        {"kb_id": CARD, "layer": "corpus", "doc_kind": "section_exemplar",
         "title": "T", "summary": "S."}, "Body.", PROV, {})
    return store


def _p(kind, **extra):
    return {"proposal_id": "prop_0123456789ab", "status": "proposed",
            "source": {"door": "flywheel", "pursuit_id": "pur_x"},
            "target": "corpus", "kind": kind, **extra}


def test_home_of_names_every_kind(store):
    text = {"text": {"before": "a", "after": "b"}}
    assert home_of(store, _p("update_card", kb_id=CARD, diff=text))["kind"] == "card_lesson"
    assert home_of(store, _p("update_card", kb_id=CARD,
                             diff={"summary": {"after": "x"}}))["kind"] == "card_field"
    both = home_of(store, _p("update_card", kb_id=CARD,
                             diff={"summary": {"after": "x"}, **text}))
    assert both["kind"] == "card_field" and "lesson" in both["label"]
    assert home_of(store, _p("update_card", kb_id="kb_gone00001",
                             diff=text))["kind"] == "none"
    assert home_of(store, _p("update_card", diff=text))["kind"] == "note"
    for kind in NOTE_KINDS:
        home = home_of(store, _p(kind, target="playbook", diff=text))
        assert home["kind"] == "note" and "playbook" in home["label"]
    assert home_of(store, _p("deprecate_card", kb_id=CARD))["kind"] == "deprecate"
    assert home_of(store, _p("deprecate_card", kb_id="kb_gone00001"))["kind"] == "none"
    fact = home_of(store, _p("new_card", target="fact_sheet",
                             diff={"body": {"after": "Q: a\nA: b"}}))
    assert fact["kind"] == "new_card"
    assert fact["needs_fill"] == ["owner", "verified_date"]
    corpus = home_of(store, _p("new_card", diff={"body": {"after": "x"},
                                                 "layer": {"after": "corpus"}}))
    assert corpus["needs_fill"] == []
    back = home_of(store, _p("outcome_backlabel", kb_id=CARD))
    assert back["kind"] == "none" and "P3-4" in back["label"]
    for home in (fact, corpus, back, both):
        assert set(home) >= {"kind", "label", "needs_fill"}


def test_a_note_kind_accepts_and_is_the_record(store):
    """Accepting a playbook note writes no card; the accepted proposal
    is the note (engine/kb/notes.py reads it) and the curation log still
    records the merge exactly once."""
    proposals = ProposalStore(store.root)
    note = proposals.open(
        source={"door": "flywheel", "pursuit_id": "pur_x",
                "event_ids": ["evt_0002"]},
        target="playbook", kind="playbook_note", at=AT,
        diff={"comment": {"after": "Lead with the outcome, not the method."}},
        note="A reviewer comment on section 2.")
    snapshot = store.snapshot()
    line = merge_batch(store, [note["proposal_id"]], operator="Sam", at=AT)
    assert store.snapshot() == snapshot, "no card moved"
    assert proposals.read(note["proposal_id"])["status"] == "accepted"
    assert line["proposal_ids"] == [note["proposal_id"]]
    log = store.root / "curation-log.jsonl"
    assert len(log.read_text(encoding="utf-8").splitlines()) == 1
    with pytest.raises(CurationRefused, match="decision is made once"):
        merge_batch(store, [note["proposal_id"]], operator="Sam", at=AT)
