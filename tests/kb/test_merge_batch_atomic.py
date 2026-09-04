"""P1-21 (P26b-2): merge_batch validates the WHOLE batch before any
write. A refusal at proposal k used to leave 1..k-1 rewritten and marked
accepted with no curation-log line — the record of what changed was
exactly the thing lost. Now: a refusal applies nothing, decides nothing,
logs nothing; a failure INSIDE the apply pass still writes the line
naming what applied and why it stopped."""

import json

import pytest

from engine.kb.curation import CurationRefused, merge_batch, propose_edit
from engine.kb.store import KBStore
from engine.flywheel.proposals import ProposalStore

PROV = {"source_pursuit": "pur_x", "source_client": "Fixture County",
        "date": "2026-01-01", "ingested_by": "ingestion_agent"}
AT = "2026-09-03T10:00:00Z"
IDS = ("kb_alpha0001", "kb_beta00001", "kb_gamma0001")


def _store(root) -> KBStore:
    store = KBStore(root)
    for kb_id, title in zip(IDS, ("A", "B", "C")):
        store.write_card(
            {"kb_id": kb_id, "layer": "corpus", "doc_kind": "section_exemplar",
             "title": title, "summary": f"Summary {title}.",
             "owner": "Delivery Lead"}, f"Body {title}.", PROV, {})
    return store


def _three(store) -> list[str]:
    return [propose_edit(store, kb_id, {"summary": f"Changed {kb_id}."},
                         operator="Sam", at=AT)["proposal_id"]
            for kb_id in IDS]


def _log_lines(store) -> list[dict]:
    log = store.root / "curation-log.jsonl"
    if not log.exists():
        return []
    return [json.loads(l) for l in log.read_text(encoding="utf-8").splitlines()]


def test_a_decided_proposal_mid_batch_refuses_the_whole_batch(tmp_path):
    store = _store(tmp_path / "kb")
    pids = _three(store)
    proposals = ProposalStore(store.root)
    proposals.decide(pids[1], decision="rejected", by="Kim", at=AT)
    snapshot = store.snapshot()
    with pytest.raises(CurationRefused, match="decision is made once"):
        merge_batch(store, pids, operator="Sam", at=AT)
    assert store.snapshot() == snapshot, "nothing applied"
    assert proposals.read(pids[0])["status"] == "proposed", "nothing decided"
    assert proposals.read(pids[2])["status"] == "proposed"
    assert store.read_card(IDS[0])[0]["summary"] == "Summary A."
    assert _log_lines(store) == [], "nothing logged — nothing happened"


def test_a_missing_target_mid_batch_refuses_the_whole_batch(tmp_path):
    store = _store(tmp_path / "kb")
    pids = _three(store)
    store.delete_card(IDS[1])
    snapshot = store.snapshot()
    with pytest.raises(CurationRefused, match="no longer exists"):
        merge_batch(store, pids, operator="Sam", at=AT)
    assert store.snapshot() == snapshot
    assert ProposalStore(store.root).read(pids[0])["status"] == "proposed"
    assert _log_lines(store) == []


def test_a_diff_the_front_matter_cannot_take_is_refused_unwritten(tmp_path):
    """A diff key that is neither `text` (a lesson, P26c) nor a card
    field — merge used to write whatever the diff carried into the card
    header. Refused at validation by name, nothing applied."""
    store = _store(tmp_path / "kb")
    proposal = ProposalStore(store.root).open(
        source={"door": "flywheel", "pursuit_id": "pur_x",
                "event_ids": ["evt_0001"]},
        target="corpus", kind="update_card", at=AT, kb_id=IDS[0],
        diff={"bogus": {"before": None, "after": "new prose"}})
    good = propose_edit(store, IDS[1], {"summary": "Fine."},
                        operator="Sam", at=AT)["proposal_id"]
    with pytest.raises(CurationRefused, match="does not fit"):
        merge_batch(store, [good, proposal["proposal_id"]],
                    operator="Sam", at=AT)
    card, _ = store.read_card(IDS[0])
    assert "bogus" not in card
    assert store.read_card(IDS[1])[0]["summary"] == "Summary B."
    assert _log_lines(store) == []


def test_a_flywheel_text_diff_lands_as_a_lesson(tmp_path):
    """P26c (P1-43): the flywheel's `update_card` carries diff.text and
    a kb_id — accepting it used to be refused (P26b-2) or, before that,
    decided and changed nothing. Now the reviewer's prose lands as a
    lessons[] entry ON the cited card: steward-visible, the body and the
    rest of the front matter untouched, the events and pursuit carried,
    the accepting steward named. A lesson with no `after` refuses the
    batch unwritten."""
    store = _store(tmp_path / "kb")
    proposal = ProposalStore(store.root).open(
        source={"door": "flywheel", "pursuit_id": "pur_x",
                "event_ids": ["evt_0007"], "section_id": "sec-02"},
        target="corpus", kind="update_card", at=AT, kb_id=IDS[0],
        diff={"text": {"before": "seven mock conversions",
                       "after": "nine mock conversions"}},
        note="A reviewer edit classified 'factual'.")
    good = propose_edit(store, IDS[1], {"summary": "Fine."},
                        operator="Sam", at=AT)["proposal_id"]
    before_body = store.read_card(IDS[0])[1]
    line = merge_batch(store, [good, proposal["proposal_id"]],
                       operator="Sam", at=AT)
    card, body = store.read_card(IDS[0])
    assert body == before_body
    assert "text" not in card
    assert card["summary"] == "Summary A."
    assert card["lessons"] == [{
        "at": AT, "by": "Sam", "proposal_id": proposal["proposal_id"],
        "pursuit_id": "pur_x", "event_ids": ["evt_0007"],
        "before": "seven mock conversions", "after": "nine mock conversions",
        "note": "A reviewer edit classified 'factual'."}]
    assert store.read_card(IDS[1])[0]["summary"] == "Fine."
    assert line["proposal_ids"] == [good, proposal["proposal_id"]]
    assert _log_lines(store) == [line]
    assert ProposalStore(store.root).read(
        proposal["proposal_id"])["status"] == "accepted"

    empty = ProposalStore(store.root).open(
        source={"door": "flywheel", "pursuit_id": "pur_x",
                "event_ids": ["evt_0008"]},
        target="corpus", kind="update_card", at=AT, kb_id=IDS[2],
        diff={"text": {"before": "gone", "after": None}})
    with pytest.raises(CurationRefused, match="needs diff.text.after"):
        merge_batch(store, [empty["proposal_id"]], operator="Sam", at=AT)
    assert "lessons" not in store.read_card(IDS[2])[0]
    assert len(_log_lines(store)) == 1


def test_a_deprecation_stamps_the_card(tmp_path):
    """P26c (P1-43): accepting a deprecate_card proposal used to decide
    and change nothing (diff.status is not a card field). Now the card
    gains a deprecated block naming the steward and the proposal — and
    stays: nothing outside a purge deletes a card."""
    from engine.kb.curation import home_of, propose_deprecation
    store = _store(tmp_path / "kb")
    proposal = propose_deprecation(store, IDS[2], operator="Sam", at=AT)
    assert home_of(store, proposal)["kind"] == "deprecate"
    merge_batch(store, [proposal["proposal_id"]], operator="Kim", at=AT)
    card, body = store.read_card(IDS[2])
    assert card["deprecated"] == {"at": AT, "by": "Kim",
                                  "proposal_id": proposal["proposal_id"]}
    assert body == "Body C."
    assert store.card_exists(IDS[2])


def test_a_deprecation_of_a_missing_card_refuses_the_batch(tmp_path):
    """Pass 1 never checked that a deprecation's card still exists —
    a purge between proposing and merging would have 'succeeded'."""
    from engine.kb.curation import propose_deprecation
    store = _store(tmp_path / "kb")
    proposal = propose_deprecation(store, IDS[2], operator="Sam", at=AT)
    good = propose_edit(store, IDS[1], {"summary": "Fine."},
                        operator="Sam", at=AT)["proposal_id"]
    store.delete_card(IDS[2])
    with pytest.raises(CurationRefused, match="no longer exists"):
        merge_batch(store, [good, proposal["proposal_id"]],
                    operator="Sam", at=AT)
    assert store.read_card(IDS[1])[0]["summary"] == "Summary B."
    assert _log_lines(store) == []


def test_a_backlabel_has_no_home_yet(tmp_path):
    """outcome_backlabel has no producer and no home (P3-4): accepting
    one refuses TYPED, naming the phase, instead of deciding and
    changing nothing — refusal reads as unfinished, never as shipped."""
    store = _store(tmp_path / "kb")
    proposal = ProposalStore(store.root).open(
        source={"door": "backlabel", "pursuit_id": "pur_x"},
        target="corpus", kind="outcome_backlabel", at=AT, kb_id=IDS[0],
        diff={"outcome": {"before": "unknown", "after": "won"}})
    with pytest.raises(CurationRefused, match="P3-4"):
        merge_batch(store, [proposal["proposal_id"]], operator="Sam", at=AT)
    assert ProposalStore(store.root).read(
        proposal["proposal_id"])["status"] == "proposed"
    assert store.read_card(IDS[0])[0].get("outcome") is None
    assert _log_lines(store) == []


def test_a_corpus_new_card_keeps_its_doc_kind(tmp_path):
    """P26c: a hand-filled case block proposes a corpus card of kind
    case_study; _check_new_card used to hard-code `fact`."""
    store = _store(tmp_path / "kb")
    proposal = ProposalStore(store.root).open(
        source={"door": "flywheel", "pursuit_id": "pur_x"},
        target="corpus", kind="new_card", at=AT,
        diff={"title": {"after": "A finance cutover"},
              "body": {"after": "client: [CLIENT]\nscope: Finance"},
              "layer": {"after": "corpus"},
              "doc_kind": {"after": "case_study"},
              "grain": {"after": "chunk"}})
    merge_batch(store, [proposal["proposal_id"]], operator="Sam", at=AT)
    minted = [c for c in store.list_cards() if c["kb_id"] not in IDS]
    assert len(minted) == 1
    assert minted[0]["doc_kind"] == "case_study"
    assert minted[0]["layer"] == "corpus"
    assert "owner" not in minted[0], "a corpus card needs no vouching fill"


def test_a_failure_inside_the_apply_pass_logs_what_applied(tmp_path,
                                                          monkeypatch):
    store = _store(tmp_path / "kb")
    pids = _three(store)
    original = KBStore.update_card_front
    calls = {"n": 0}

    def flaky(self, kb_id, **fields):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("disk went away")
        return original(self, kb_id, **fields)

    monkeypatch.setattr(KBStore, "update_card_front", flaky)
    with pytest.raises(OSError):
        merge_batch(store, pids, operator="Sam", at=AT)
    lines = _log_lines(store)
    assert len(lines) == 1
    assert lines[0]["proposal_ids"] == [pids[0]], "what applied, by name"
    assert lines[0]["aborted"].startswith("OSError: disk went away")
    assert lines[0]["snapshot_before"] != lines[0]["snapshot_after"]
    proposals = ProposalStore(store.root)
    assert proposals.read(pids[0])["status"] == "accepted"
    assert proposals.read(pids[1])["status"] == "proposed"
    assert proposals.read(pids[2])["status"] == "proposed"


def test_a_clean_batch_still_writes_exactly_one_line(tmp_path):
    store = _store(tmp_path / "kb")
    pids = _three(store)
    line = merge_batch(store, pids, operator="Sam", at=AT)
    assert line["proposal_ids"] == pids
    assert "aborted" not in line
    assert _log_lines(store) == [line]
