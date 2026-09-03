"""P2-23 (P26b-1, B112), the door half: the three KB routes that take an
id from a payload or a path refuse a malformed one with 422 naming the
shape — before the store, before `merge_batch`'s `Path / pid` could turn
a non-string into a 500 (the register's TypeError case)."""

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
    app = create_app(workspace, make_caller=raising_caller,
                     now=lambda: FIXED_AT)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        sign_in(client, "Sam Steward")
        yield client


@pytest.mark.parametrize("kb_id", ["../x", "kb_ALPHA0001", "kb_a.b", "kb_", ""])
def test_propose_refuses_a_malformed_kb_id(client, kb_id):
    r = client.post("/api/kb/proposals", json={
        "kb_id": kb_id, "changes": {"summary": "x"}})
    assert r.status_code == 422, r.text
    assert "not a kb_id" in r.json()["detail"]


def test_propose_still_404s_a_well_formed_unknown_id(client):
    r = client.post("/api/kb/proposals", json={
        "kb_id": "kb_0123456789", "changes": {"summary": "x"}})
    assert r.status_code == 404
    r = client.post("/api/kb/proposals", json={
        "kb_id": "kb_short", "changes": {"summary": "x"}})
    assert r.status_code == 404  # a readable id is a valid shape


@pytest.mark.parametrize("ids", [[7], ["prop_0123456789ab", None], ["../x"],
                                 ["PROP_0123456789AB"]])
def test_merge_refuses_a_malformed_element(client, ids):
    r = client.post("/api/kb/proposals/merge",
                    json={"proposal_ids": ids})
    assert r.status_code == 422, r.text
    assert "not a proposal_id" in r.json()["detail"]


def test_decide_refuses_a_malformed_path_id(client):
    r = client.post("/api/kb/proposals/..%2Fx/decide",
                    json={"decision": "rejected"})
    assert r.status_code in (404, 422)
    r = client.post("/api/kb/proposals/prop_not.hex/decide",
                    json={"decision": "rejected"})
    assert r.status_code == 422 and "not a proposal_id" in r.json()["detail"]
