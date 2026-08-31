"""The org registry over HTTP (P17/C6): create → list → note, operator-
attributed; the note door's refusals surface as 409s, never silent."""

import pytest
from fastapi.testclient import TestClient

from engine.web.server import create_app
from engine.workspace import orgs
from tests.web.conftest import FIXED_AT, sign_in


@pytest.fixture(scope="module")
def org_client(tmp_path_factory):
    ws = tmp_path_factory.mktemp("web-orgs") / "ws"
    app = create_app(ws, now=lambda: FIXED_AT)
    client = TestClient(app)
    client.__enter__()
    sign_in(client, "Ollie Operator")
    yield client, ws
    client.__exit__(None, None, None)


def test_create_list_note_roundtrip(org_client):
    client, ws = org_client
    created = client.post("/api/orgs",
                          json={"name": "Synthetic Health System"}).json()
    assert created["org_id"] == "org_0001"
    assert created["known_as"] == ["Synthetic Health System"]
    assert created["created_by"] == "Ollie Operator"

    listed = client.get("/api/orgs").json()["orgs"]
    assert [o["org_id"] for o in listed] == ["org_0001"]

    note = client.post("/api/orgs/org_0001/notes",
                       json={"title": "Reference preference",
                             "body": "They asked for peer references "
                                     "in the same vertical."}).json()
    assert note["kb_id"].startswith("okb_")
    assert note["by"] == "Ollie Operator"
    card, _ = orgs.org_store(ws, "org_0001").read_card(note["kb_id"])
    assert card["content_origin"] == "human_authored"


def test_note_refusals_are_409s(org_client):
    client, _ws = org_client
    assert client.post("/api/orgs/org_0001/notes",
                       json={"title": "", "body": "x"}).status_code == 409
    assert client.post("/api/orgs/org_9999/notes",
                       json={"title": "t", "body": "b"}).status_code == 409
    assert client.post("/api/orgs", json={"name": " "}).status_code == 409
