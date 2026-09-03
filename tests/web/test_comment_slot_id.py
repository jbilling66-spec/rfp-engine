"""P3-14 (P26b-1, B112): a comment's `slot_id` — on the GUEST door and
on the internal door alike — must be a slot of the section it targets;
a foreign or unknown slot is refused 400 (and, on the guest door, logged
as a denied access), so a later revision round can never be tagged onto
the wrong target."""

import pytest
from fastapi.testclient import TestClient

from engine.web.server import create_app
from tests.validation.fixtures.validations import run_validation_package
from tests.web.conftest import FIXED_AT, raising_caller, sign_in

EXPIRES = "2026-08-16T09:00:00"


@pytest.fixture(scope="module")
def wired(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("web-slot-ids")
    pursuit, report, _ = run_validation_package(tmp)
    assert report.status == "complete"
    app = create_app(tmp, make_caller=raising_caller, now=lambda: FIXED_AT)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        sign_in(client, "Cora Commenter")
        pid = pursuit.pursuit_id
        link = client.post(f"/api/pursuits/{pid}/share", json={
            "label": "outside counsel", "expires_at": EXPIRES}).json()
        yield client, pursuit, link


def _sections(pursuit):
    plan = pursuit.read_artifact("plan.json")
    return plan["sections"]


def test_internal_door_refuses_a_foreign_or_unknown_slot(wired):
    client, pursuit, _ = wired
    pid = pursuit.pursuit_id
    sections = _sections(pursuit)
    sid, own = sections[0]["section_id"], sections[0]["slot_ids"][0]
    r = client.post(f"/api/pursuits/{pid}/comments", json={
        "kind": "comment", "section_id": sid, "slot_id": "slot_nope",
        "text": "t"})
    assert r.status_code == 400 and "not a slot of section" in r.json()["detail"]
    foreign = next((s["slot_ids"][0] for s in sections[1:] if s.get("slot_ids")), None)
    if foreign is not None:
        r = client.post(f"/api/pursuits/{pid}/comments", json={
            "kind": "comment", "section_id": sid, "slot_id": foreign,
            "text": "t"})
        assert r.status_code == 400
    r = client.post(f"/api/pursuits/{pid}/comments", json={
        "kind": "comment", "section_id": sid, "slot_id": own,
        "text": "lands"})
    assert r.status_code == 200, r.text
    r = client.post(f"/api/pursuits/{pid}/comments", json={
        "kind": "comment", "section_id": sid, "text": "section-level"})
    assert r.status_code == 200, r.text


def test_guest_door_refuses_and_logs(wired):
    client, pursuit, link = wired
    sections = _sections(pursuit)
    sid, own = sections[0]["section_id"], sections[0]["slot_ids"][0]
    r = client.post(f"/share/{link['token']}/comments", json={
        "display_name": "Dana Counsel", "section_id": sid,
        "slot_id": "slot_nope", "text": "hello"})
    assert r.status_code == 400 and "not a slot of section" in r.json()["detail"]
    access = (pursuit.root / "share" / "access.jsonl").read_text()
    assert "slot not in section" in access
    r = client.post(f"/share/{link['token']}/comments", json={
        "display_name": "Dana Counsel", "section_id": sid,
        "slot_id": own, "text": "on the slot"})
    assert r.status_code == 200, r.text
