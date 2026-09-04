"""The KB curation surface (c20).

v1's governance spine reimplemented — every door proposes, a steward
merges, nothing is erased, restricted material is an inline note rather
than a hidden filter — with the three screen failures fixed: no search,
no in-place edit, and (the one that actually bit) no web approve door at
all, which left imported content published, valid and invisible to every
draft.
"""

import json

import pytest
from fastapi.testclient import TestClient

from engine.kb.store import KBStore
from engine.web.server import create_app
from tests.web.conftest import FIXED_AT, raising_caller, sign_in

PROV = {"source_pursuit": "pur_x", "source_client": "Fixture County",
        "date": "2026-01-01", "ingested_by": "ingestion_agent"}


@pytest.fixture
def client(tmp_path):
    workspace = tmp_path / "ws"
    store = KBStore(workspace / "kb")
    store.write_card(
        {"kb_id": "kb_alpha0001", "layer": "corpus",
         "doc_kind": "section_exemplar", "title": "Data Migration Approach",
         "summary": "Seven mock conversions.", "owner": "Delivery Lead"},
        "Body one.", PROV, {})
    store.write_card(
        {"kb_id": "kb_stale0001", "layer": "fact_sheet", "doc_kind": "fact",
         "title": "Lapsed certification", "summary": "Prior platform.",
         "owner": "Compliance Lead", "verified_date": "2024-01-01",
         "review_due": "2025-01-01"},
        "Body two.", PROV, {})
    store.write_card(
        {"kb_id": "kb_restr0001", "layer": "corpus", "doc_kind": "past_response",
         "title": "Escalation runbook", "summary": "Named engagement.",
         "owner": "Delivery Lead", "use_restriction": True,
         "sensitivity": "restricted"},
        "Body three.", PROV, {})

    app = create_app(workspace, make_caller=raising_caller,
                     now=lambda: FIXED_AT)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        sign_in(client, "Sam Steward")
        yield client


def _proposals(client, **params):
    return client.get("/api/kb/proposals", params=params).json()["proposals"]


# ------------------------------------------------------------ the screen

def test_search_filter_and_sort_exist(client):
    """v1's grid had none of these, which made it a viewer rather than a
    curation surface — fine at 17 cards, useless at 500."""
    everything = client.get("/api/kb/cards").json()["cards"]
    assert len(everything) == 3

    found = client.get("/api/kb/cards", params={"q": "migration"}).json()
    assert [c["kb_id"] for c in found["cards"]] == ["kb_alpha0001"]

    facts = client.get("/api/kb/cards", params={"layer": "fact_sheet"}).json()
    assert [c["kb_id"] for c in facts["cards"]] == ["kb_stale0001"]

    stale = client.get("/api/kb/cards",
                       params={"staleness": "past_due"}).json()
    assert [c["kb_id"] for c in stale["cards"]] == ["kb_stale0001"]


def test_restricted_material_is_an_inline_note_never_hidden(client):
    """A reviewer who cannot see that a card is restricted cannot reason
    about why it never appears in drafts. The fact is shown; the
    provenance CONTENT stays behind the access log."""
    cards = {c["kb_id"]: c for c in
             client.get("/api/kb/cards").json()["cards"]}
    notes = " ".join(cards["kb_restr0001"]["notes"])
    assert "reuse restricted" in notes
    assert "access-logged" in notes
    body = json.dumps(cards)
    assert "Fixture County" not in body, "no restricted CONTENT on the list"


def test_card_detail_shows_citations_computed_live(client):
    detail = client.get("/api/kb/cards/kb_alpha0001").json()
    assert detail["card"]["kb_id"] == "kb_alpha0001"
    assert detail["body"].strip() == "Body one."
    assert detail["cite_count"] == 0, "nothing has cited it in this workspace"


def test_a_missing_card_is_a_404_not_an_empty_shell(client):
    assert client.get("/api/kb/cards/kb_nope").status_code == 404


# ---------------------------------------------------------- edit as proposal

def test_an_in_place_edit_mints_a_proposal_and_writes_no_card(client,
                                                              tmp_path):
    """v1 had no in-place edit at all — you proposed a superseding copy,
    a heavier act than fixing a typo deserves. Here the edit is easy AND
    still lands as a diff a steward sees."""
    response = client.post("/api/kb/proposals", json={
        "kb_id": "kb_alpha0001",
        "changes": {"summary": "Seven mock conversions, reconciled."}})
    assert response.status_code == 200
    proposal = response.json()
    assert proposal["status"] == "proposed"
    assert proposal["source"]["door"] == "card_edit"
    assert proposal["source"]["operator"] == "Sam Steward"
    assert proposal["diff"]["summary"]["before"] == "Seven mock conversions."

    detail = client.get("/api/kb/cards/kb_alpha0001").json()
    assert detail["card"]["summary"] == "Seven mock conversions.", (
        "the card must be untouched until a steward merges")


def test_governance_fields_refuse_an_edit(client):
    refused = client.post("/api/kb/proposals", json={
        "kb_id": "kb_alpha0001",
        "changes": {"use_restriction": True}})
    assert refused.status_code == 409
    assert "governance decision" in refused.json()["detail"]


def test_an_edit_that_changes_nothing_is_refused(client):
    refused = client.post("/api/kb/proposals", json={
        "kb_id": "kb_alpha0001",
        "changes": {"summary": "Seven mock conversions."}})
    assert refused.status_code == 409
    assert "nothing changed" in refused.json()["detail"]


# ------------------------------------------------------------- deprecation

def test_deprecation_is_refused_while_cited_and_names_the_pursuit(tmp_path):
    """'Something depends on this' is unactionable without knowing what."""
    from engine.kb.curation import CurationRefused, propose_deprecation

    store = KBStore(tmp_path / "kb")
    store.write_card({"kb_id": "kb_cited0001", "layer": "corpus",
                      "summary": "S"}, "B", PROV, {})
    records = [{"run_id": "run_0001", "pursuit_id": "pur_live", "seq": 1,
                "ts": FIXED_AT, "record_type": "kb_retrieval",
                "kb": {"query": "q", "step": "cite",
                       "cards_returned": ["kb_cited0001"],
                       "cards_opened": ["kb_cited0001"],
                       "cards_cited": ["kb_cited0001"],
                       "excluded": [], "empty_result": False},
                "target": {"section_id": "s1"}}]
    with pytest.raises(CurationRefused) as caught:
        propose_deprecation(store, "kb_cited0001", operator="s",
                            at=FIXED_AT, records=records)
    assert "pur_live" in str(caught.value)
    assert "Supersede it instead" in str(caught.value)


def test_an_uncited_card_deprecates_as_a_proposal_not_a_delete(client):
    response = client.post("/api/kb/proposals", json={
        "kb_id": "kb_stale0001", "action": "deprecate"})
    assert response.status_code == 200
    assert response.json()["kind"] == "deprecate_card"
    # Nothing is erased — the card is still there pending the decision.
    assert client.get("/api/kb/cards/kb_stale0001").status_code == 200


def test_accepting_a_deprecation_stamps_not_deletes(client):
    """P26c (P1-43): accepting the deprecation used to decide and change
    nothing. Now the card carries a `deprecated` block, the row says so,
    and the card still answers — nothing outside a purge deletes."""
    proposal = client.post("/api/kb/proposals", json={
        "kb_id": "kb_stale0001", "action": "deprecate"}).json()
    decided = client.post(
        f"/api/kb/proposals/{proposal['proposal_id']}/decide",
        json={"decision": "accepted"})
    assert decided.status_code == 200, decided.text
    detail = client.get("/api/kb/cards/kb_stale0001")
    assert detail.status_code == 200
    assert detail.json()["card"]["deprecated"]["proposal_id"] == (
        proposal["proposal_id"])
    assert any("deprecated" in n for n in detail.json()["notes"])
    row = [r for r in client.get("/api/kb/cards").json()["cards"]
           if r["kb_id"] == "kb_stale0001"][0]
    assert row["deprecated"] is True


def test_legal_hold_blocks_deprecation(tmp_path):
    from engine.kb.curation import CurationRefused, propose_deprecation

    store = KBStore(tmp_path / "kb")
    store.write_card({"kb_id": "kb_held00001", "layer": "corpus",
                      "summary": "S", "legal_hold": True}, "B", PROV, {})
    with pytest.raises(CurationRefused) as caught:
        propose_deprecation(store, "kb_held00001", operator="s", at=FIXED_AT)
    assert "legal hold" in str(caught.value)


# ------------------------------------------------- approve on the SAME surface

def test_mint_and_approve_ship_on_one_surface(client):
    """THE v1 failure this fixes: it had no web route for approval, so
    the only approve door was a terminal command and imported content
    sat published, valid and invisible to every draft."""
    proposal = client.post("/api/kb/proposals", json={
        "kb_id": "kb_alpha0001",
        "changes": {"summary": "Seven mock conversions, reconciled."}}).json()

    assert len(_proposals(client, status="proposed")) == 1
    decided = client.post(
        f"/api/kb/proposals/{proposal['proposal_id']}/decide",
        json={"decision": "accepted"})
    assert decided.status_code == 200

    detail = client.get("/api/kb/cards/kb_alpha0001").json()
    assert detail["card"]["summary"] == "Seven mock conversions, reconciled."
    assert _proposals(client, status="proposed") == []


def test_a_rejection_keeps_the_proposal_and_the_card(client):
    proposal = client.post("/api/kb/proposals", json={
        "kb_id": "kb_alpha0001", "changes": {"summary": "Rewritten."}}).json()
    client.post(f"/api/kb/proposals/{proposal['proposal_id']}/decide",
                json={"decision": "rejected", "note": "wrong"})
    rejected = _proposals(client, status="rejected")
    assert len(rejected) == 1 and rejected[0]["decided"]["note"] == "wrong"
    assert client.get("/api/kb/cards/kb_alpha0001").json()[
        "card"]["summary"] == "Seven mock conversions."


def test_a_batch_merge_writes_one_curation_log_line(client, tmp_path):
    first = client.post("/api/kb/proposals", json={
        "kb_id": "kb_alpha0001", "changes": {"summary": "One."}}).json()
    second = client.post("/api/kb/proposals", json={
        "kb_id": "kb_stale0001", "changes": {"summary": "Two."}}).json()

    merged = client.post("/api/kb/proposals/merge", json={
        "proposal_ids": [first["proposal_id"], second["proposal_id"]]}).json()
    assert merged["by"] == "Sam Steward"
    assert merged["snapshot_before"] != merged["snapshot_after"]

    log = (tmp_path / "ws" / "kb" / "curation-log.jsonl")
    lines = [json.loads(line) for line in
             log.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 1, "one batch, one line — not one line per card"
    assert len(lines[0]["proposal_ids"]) == 2


def test_concurrent_merge_through_the_route(client, monkeypatch):
    """P1-40 at the door: two stewards' merges of one proposal, in
    flight together on the server's thread pool — one 200, one 409,
    never two acceptances. The write is slowed so the requests overlap."""
    import threading
    import time

    from engine.kb.store import KBStore

    proposal = client.post("/api/kb/proposals", json={
        "kb_id": "kb_alpha0001", "changes": {"summary": "Raced."}}).json()
    pid = proposal["proposal_id"]
    original = KBStore.update_card_front

    def slow(self, kb_id, **fields):
        time.sleep(0.3)
        return original(self, kb_id, **fields)

    monkeypatch.setattr(KBStore, "update_card_front", slow)
    statuses: list[int] = []

    def merge():
        statuses.append(client.post("/api/kb/proposals/merge",
                                    json={"proposal_ids": [pid]}).status_code)

    threads = [threading.Thread(target=merge) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert sorted(statuses) == [200, 409], statuses


def test_accept_then_reject_is_refused(client, tmp_path):
    """P1-39: the reject door used to overwrite an accepted proposal's
    decided block while the curation log still recorded the merge."""
    proposal = client.post("/api/kb/proposals", json={
        "kb_id": "kb_alpha0001", "changes": {"summary": "Settled."}}).json()
    pid = proposal["proposal_id"]
    assert client.post(f"/api/kb/proposals/{pid}/decide",
                       json={"decision": "accepted"}).status_code == 200
    again = client.post(f"/api/kb/proposals/{pid}/decide",
                        json={"decision": "rejected", "note": "changed my mind"})
    assert again.status_code == 409
    assert "decision is made once" in again.json()["detail"]
    kept = client.get("/api/kb/proposals", params={"status": "accepted"}).json()
    decided = [p for p in kept["proposals"] if p["proposal_id"] == pid][0]
    assert decided["decided"]["decision"] == "accepted"
    assert "note" not in decided["decided"]
    log = tmp_path / "ws" / "kb" / "curation-log.jsonl"
    assert len(log.read_text(encoding="utf-8").splitlines()) == 1


def test_rejecting_an_unknown_proposal_is_404(client):
    gone = client.post("/api/kb/proposals/prop_0123456789ab/decide",
                       json={"decision": "rejected"})
    assert gone.status_code == 404


def test_deciding_twice_is_refused(client):
    proposal = client.post("/api/kb/proposals", json={
        "kb_id": "kb_alpha0001", "changes": {"summary": "Once."}}).json()
    pid = proposal["proposal_id"]
    client.post(f"/api/kb/proposals/{pid}/decide",
                json={"decision": "accepted"})
    again = client.post("/api/kb/proposals/merge",
                        json={"proposal_ids": [pid]})
    assert again.status_code == 409
    assert "decision is made once" in again.json()["detail"]


def test_every_mutating_curation_route_needs_an_operator(tmp_path):
    """Reads are open on a localhost bind; writes are not."""
    from engine.web.auth import AuthSeam

    workspace = tmp_path / "ws"
    KBStore(workspace / "kb").write_card(
        {"kb_id": "kb_alpha0001", "layer": "corpus", "summary": "S"},
        "B", PROV, {})
    app = create_app(workspace, make_caller=raising_caller,
                     now=lambda: FIXED_AT)
    with TestClient(app, base_url="http://127.0.0.1") as anonymous:
        assert anonymous.get("/api/kb/cards").status_code == 200
        assert anonymous.post("/api/kb/proposals", json={
            "kb_id": "kb_alpha0001", "changes": {"summary": "x"}
        }).status_code == 401
        assert anonymous.post("/api/kb/proposals/merge", json={
            "proposal_ids": ["prop_x"]}).status_code == 401


# ------------------------------------------- P26c: the inbox names the home

@pytest.fixture
def inbox(tmp_path):
    workspace = tmp_path / "ws"
    store = KBStore(workspace / "kb")
    store.write_card(
        {"kb_id": "kb_alpha0001", "layer": "corpus",
         "doc_kind": "section_exemplar", "title": "Data Migration Approach",
         "summary": "Seven mock conversions.", "owner": "Delivery Lead"},
        "Body one.", PROV, {})
    app = create_app(workspace, make_caller=raising_caller,
                     now=lambda: FIXED_AT)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        sign_in(client, "Sam Steward")
        yield client, store


GAP = {"gap_id": "gap_pur_x_01", "status": "answered",
       "question_to_human": "How many validated waves?", "answer": "Four."}


def test_the_inbox_names_every_proposals_home(inbox):
    """P1-43 (item 3): every row carries `home` — the kind, the label,
    the card when there is one, and the fields a fact card needs — so a
    steward approves a visible change and knows where it lands. An
    accepted note shows among the accepted rows as the note it is."""
    from engine.flywheel.proposals import ProposalStore
    from engine.kb.curation import propose_gap_answer_card

    client, store = inbox
    proposals = ProposalStore(store.root)
    field_ = client.post("/api/kb/proposals", json={
        "kb_id": "kb_alpha0001",
        "changes": {"summary": "Eight."}}).json()["proposal_id"]
    dep = client.post("/api/kb/proposals", json={
        "kb_id": "kb_alpha0001", "action": "deprecate"}).json()["proposal_id"]
    lesson = proposals.open(
        source={"door": "flywheel", "pursuit_id": "pur_x",
                "event_ids": ["evt_0001"], "external": True},
        target="corpus", kind="update_card", at=FIXED_AT,
        kb_id="kb_alpha0001",
        diff={"text": {"before": "seven", "after": "nine"}})["proposal_id"]
    note = proposals.open(
        source={"door": "flywheel", "pursuit_id": "pur_x",
                "event_ids": ["evt_0002"]},
        target="playbook", kind="playbook_note", at=FIXED_AT,
        diff={"comment": {"after": "Lead with the outcome."}})["proposal_id"]
    fact = propose_gap_answer_card(store.root, gap=GAP, pursuit_id="pur_x",
                                   operator="Astrid", at=FIXED_AT)
    rows = {p["proposal_id"]: p for p in _proposals(client, status="proposed")}
    assert rows[field_]["home"]["kind"] == "card_field"
    assert rows[lesson]["home"]["kind"] == "card_lesson"
    assert rows[lesson]["home"]["kb_id"] == "kb_alpha0001"
    assert "lesson" in rows[lesson]["home"]["label"]
    assert rows[lesson]["source"]["external"] is True
    assert rows[dep]["home"]["kind"] == "deprecate"
    assert rows[note]["home"]["kind"] == "note"
    assert "playbook" in rows[note]["home"]["label"]
    assert rows[fact]["home"]["kind"] == "new_card"
    assert rows[fact]["home"]["needs_fill"] == ["owner", "verified_date"]
    assert all(set(r["home"]) >= {"kind", "label", "needs_fill"}
               for r in rows.values())
    r = client.post(f"/api/kb/proposals/{note}/decide",
                    json={"decision": "accepted"})
    assert r.status_code == 200, r.text
    accepted = _proposals(client, status="accepted")
    assert [p["proposal_id"] for p in accepted
            if p["home"]["kind"] == "note"] == [note]


def test_a_fact_card_accepts_from_the_ui_with_fills(inbox):
    """P1-43: the decide door takes `fills` — without them a fact card
    refuses by name (as before, but now the row asks); with them the
    card mints, human-vouched. A malformed fills is 422, typed."""
    from engine.kb.curation import propose_gap_answer_card

    client, store = inbox
    fact = propose_gap_answer_card(store.root, gap=GAP, pursuit_id="pur_x",
                                   operator="Astrid", at=FIXED_AT)
    url = f"/api/kb/proposals/{fact}/decide"
    r = client.post(url, json={"decision": "accepted"})
    assert r.status_code == 409 and "owner and" in r.json()["detail"]
    assert len(store.list_cards()) == 1, "nothing minted"
    r = client.post(url, json={"decision": "accepted", "fills": "x"})
    assert r.status_code == 422
    r = client.post(url, json={"decision": "accepted", "fills": {
        fact: {"owner": "Sam Steward", "verified_date": "2026-09-04"}}})
    assert r.status_code == 200, r.text
    minted = [c for c in store.list_cards() if c["kb_id"] != "kb_alpha0001"]
    assert len(minted) == 1
    assert minted[0]["layer"] == "fact_sheet"
    assert minted[0]["owner"] == "Sam Steward"
    assert minted[0]["verified_date"] == "2026-09-04"
    assert _proposals(client, status="proposed") == []
