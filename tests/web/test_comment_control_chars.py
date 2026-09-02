"""P26a Group B (P2-29b), the two comment doors over HTTP: a control
character in an operator comment, an operator edit, or a GUEST comment
is a 422 at the door — nothing is pended, so the envelope can never
inherit it through a round."""

import pytest
from fastapi.testclient import TestClient

from engine.web.events import EventsLane
from engine.web.server import create_app
from tests.validation.fixtures.validations import run_validation_package
from tests.web.conftest import FIXED_AT, raising_caller, sign_in

EXPIRES = "2026-08-16T09:00:00"


@pytest.fixture(scope="module")
def reviewed(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("web-ctrl-comments")
    pursuit, report, _ = run_validation_package(tmp)
    assert report.status == "complete"
    app = create_app(tmp, make_caller=raising_caller, now=lambda: FIXED_AT)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        sign_in(client, "Cora Commenter")
        yield client, pursuit


def _section_id(pursuit) -> str:
    plan = pursuit.read_artifact("plan.json")
    return plan["sections"][0]["section_id"]


def test_operator_comment_and_edit_doors_refuse(reviewed):
    client, pursuit = reviewed
    pid, sid = pursuit.pursuit_id, _section_id(pursuit)
    r = client.post(f"/api/pursuits/{pid}/comments", json={
        "kind": "comment", "section_id": sid, "text": "bad\x0bchar"})
    assert r.status_code == 422 and "control character" in r.json()["detail"]
    r = client.post(f"/api/pursuits/{pid}/comments", json={
        "kind": "edit", "section_id": sid, "before": "a", "after": "b\x0c"})
    assert r.status_code == 422 and "after: control" in r.json()["detail"]
    assert EventsLane(pursuit).pending() == []


def test_guest_comment_door_refuses(reviewed):
    client, pursuit = reviewed
    pid = pursuit.pursuit_id
    link = client.post(f"/api/pursuits/{pid}/share", json={
        "label": "synthetic counsel", "expires_at": EXPIRES}).json()
    guest = TestClient(client.app, base_url="http://127.0.0.1")
    r = guest.post(f"/share/{link['token']}/comments", json={
        "display_name": "Guest", "section_id": _section_id(pursuit),
        "text": "looks\x0bfine"})
    assert r.status_code == 422, r.text
    assert "control character" in r.json()["detail"]
    assert EventsLane(pursuit).pending() == []
