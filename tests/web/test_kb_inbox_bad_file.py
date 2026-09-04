"""M-30 (P26b-2): one hand-authored bad file under kb/proposals/ used to
500 the steward inbox. Now the door answers 409 naming the file — the
record is evidence — and every other proposal is still there once it is
dealt with."""

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
         "doc_kind": "section_exemplar", "title": "A", "summary": "One.",
         "owner": "Delivery Lead"}, "Body.", PROV, {})
    app = create_app(workspace, make_caller=raising_caller,
                     now=lambda: FIXED_AT)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        sign_in(client, "Sam Steward")
        yield client


def test_a_bad_proposal_file_is_named_not_a_500(client, tmp_path):
    good = client.post("/api/kb/proposals", json={
        "kb_id": "kb_alpha0001", "changes": {"summary": "Two."}}).json()
    bad = tmp_path / "ws" / "kb" / "proposals" / "prop_deadbeef0000.json"
    bad.write_text("{\"status\": \"proposed\",", encoding="utf-8")
    inbox = client.get("/api/kb/proposals")
    assert inbox.status_code == 409
    assert "prop_deadbeef0000.json" in inbox.json()["detail"]
    merge = client.post("/api/kb/proposals/merge",
                        json={"proposal_ids": [good["proposal_id"]]})
    assert merge.status_code == 200, "a merge reads only its own ids"
    bad.unlink()
    inbox = client.get("/api/kb/proposals", params={"status": "accepted"})
    assert [p["proposal_id"] for p in inbox.json()["proposals"]] == [
        good["proposal_id"]]
