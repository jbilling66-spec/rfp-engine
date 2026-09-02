"""P27 wave 1 (M-9): the actor's role is the SESSION's. Declared mode
takes it at sign-in (a declarable role, nothing preselected in the
shell); header mode takes it from the proxy's role header, required only
by the doors that record one; a client-supplied `actor_role` is refused
on every door — the session names the role, so the effort/cost metrics
aggregate by a role a human chose, never a hardcoded default."""

import json

import pytest
from fastapi.testclient import TestClient

from engine.web.auth import DECLARABLE_ROLES
from engine.web.server import create_app
from tests.web.conftest import FIXED_AT, raising_caller, sign_in


def test_declarable_roles_are_the_enum_minus_the_guest_role():
    assert "external_reviewer" not in DECLARABLE_ROLES
    assert set(DECLARABLE_ROLES) >= {"pursuit_lead", "sme", "partner",
                                     "proposal_manager", "contracts",
                                     "fact_sheet_steward", "other"}


@pytest.mark.parametrize("payload", [
    {"name": "Sam Lead"},                                   # no role
    {"name": "Sam Lead", "role": "ceo"},                    # unknown
    {"name": "Sam Lead", "role": "external_reviewer"},      # guest role
    {"name": "Sam Lead", "role": 7},                        # wrong type
])
def test_sign_in_requires_a_declarable_role(offline_app, payload):
    r = offline_app.post("/api/session", json=payload)
    assert r.status_code == 422, r.text
    assert "role" in r.json()["detail"]
    assert offline_app.get("/api/session").json()["operator"] is None


def test_whoami_carries_the_role_and_the_declarable_list(offline_app):
    sign_in(offline_app, "Pat Partner", role="partner")
    who = offline_app.get("/api/session").json()
    assert who == {"operator": "Pat Partner", "role": "partner",
                   "roles": list(DECLARABLE_ROLES)}


def test_an_event_lands_with_the_session_role(offline_app):
    sign_in(offline_app, "Sky Sme", role="sme")
    offline_app.post("/api/pursuits", json={"pursuit_id": "pur_role"})
    r = offline_app.post("/api/pursuits/pur_role/effort", json={
        "measurement": "manual", "confirmed_minutes": 15})
    assert r.status_code == 200, r.text
    assert r.json()["actor_role"] == "sme"
    ws = offline_app.app.state.workspace
    events = [json.loads(l) for l in
              (ws / "pur_role" / "events" / "events.jsonl")
              .read_text(encoding="utf-8").splitlines()]
    assert [e["actor_role"] for e in events] == ["sme"]


ROLE_DOORS = [
    ("post", "/api/pursuits/pur_role/comments",
     {"kind": "comment", "section_id": "s", "text": "t"}),
    ("post", "/api/pursuits/pur_role/waivers",
     {"claim_id": "c", "reason": "r"}),
    ("post", "/api/pursuits/pur_role/events",
     {"kind": "accept", "section_id": "s"}),
    ("post", "/api/pursuits/pur_role/accept", {}),
    ("post", "/api/pursuits/pur_role/outcome", {"result": "won"}),
    ("post", "/api/pursuits/pur_role/effort",
     {"measurement": "manual", "confirmed_minutes": 5}),
    ("post", "/api/pursuits/pur_role/gate0", {"decision": "approved"}),
]


@pytest.mark.parametrize("method, path, body", ROLE_DOORS,
                         ids=[d[1].rsplit("/", 1)[1] for d in ROLE_DOORS])
def test_a_client_actor_role_is_refused_on_every_role_door(
        offline_app, method, path, body):
    """Refused BEFORE any state is consulted (the _at boundary, P0-11's
    idiom) — so a bare pursuit with no plan is enough to prove it, and
    no event lands."""
    sign_in(offline_app, "Lee Lead", role="pursuit_lead")
    offline_app.post("/api/pursuits", json={"pursuit_id": "pur_role"})
    r = getattr(offline_app, method)(path, json={**body,
                                                 "actor_role": "partner"})
    assert r.status_code == 422, (path, r.status_code, r.text)
    assert "session names the role" in r.json()["detail"]
    ws = offline_app.app.state.workspace
    assert not (ws / "pur_role" / "events" / "events.jsonl").exists()


def test_header_mode_reads_the_role_header_only_on_role_doors(tmp_path):
    """The A5 seam: the proxy sets X-Auth-User for identity and
    X-Auth-Role for the role. A door that records no role still works
    under the user header alone (the existing seam test's case); a role
    door 401s naming the role header, and carries the role when set."""
    cfg = tmp_path / "web.yaml"
    cfg.write_text("auth:\n  mode: header\n  header_name: X-Auth-User\n"
                   "  role_header_name: X-Auth-Role\n", encoding="utf-8")
    app = create_app(tmp_path / "ws", make_caller=raising_caller,
                     auth_config=cfg, now=lambda: FIXED_AT)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        user = {"X-Auth-User": "Proxy Person"}
        r = client.post("/api/pursuits", json={"pursuit_id": "pur_h"},
                        headers=user)
        assert r.status_code == 200, r.text
        r = client.post("/api/pursuits/pur_h/effort", headers=user, json={
            "measurement": "manual", "confirmed_minutes": 5})
        assert r.status_code == 401
        assert "X-Auth-Role" in r.json()["detail"]
        r = client.post("/api/pursuits/pur_h/effort",
                        headers={**user, "X-Auth-Role": "ceo"}, json={
                            "measurement": "manual", "confirmed_minutes": 5})
        assert r.status_code == 422
        r = client.post("/api/pursuits/pur_h/effort",
                        headers={**user, "X-Auth-Role": "contracts"}, json={
                            "measurement": "manual", "confirmed_minutes": 5})
        assert r.status_code == 200, r.text
        assert r.json()["actor_role"] == "contracts"
        who = client.get("/api/session",
                         headers={**user, "X-Auth-Role": "contracts"}).json()
        assert who["operator"] == "Proxy Person" and who["role"] == "contracts"
