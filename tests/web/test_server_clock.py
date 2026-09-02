"""P0-11 (P26a Group D): the SERVER stamps every mutating door's clock. A
client-supplied `at` in a mutating payload is a 422 — the door is
visibly closed, never silently ignoring — while read-time staleness
probes keep their parameter; the gate stamp equals the app's injected
clock; and the ping lane's escalation is measured on the server clock
(P2-47), with naive and aware timestamps subtracting safely (P2-48)."""

from datetime import timedelta

import pytest

from engine.web import pings
from tests.web.conftest import FIXED_AT, sign_in



@pytest.fixture
def client(offline_app):
    sign_in(offline_app)
    offline_app.post("/api/pursuits", json={"pursuit_id": "pur_clock"})
    return offline_app


@pytest.mark.parametrize("method, path, payload", [
    ("post", "/api/pursuits", {"pursuit_id": "pur_late"}),
    ("post", "/api/pursuits/pur_clock/jobs", {"kind": "advance"}),
    ("post", "/api/pursuits/pur_clock/gate0", {"decision": "approved"}),
    ("post", "/api/pursuits/pur_clock/gate1", {"decision": "approved"}),
    ("post", "/api/pursuits/pur_clock/gate2", {"decision": "approved"}),
    ("post", "/api/pursuits/pur_clock/waivers",
     {"claim_id": "c", "reason": "r"}),
    ("post", "/api/pursuits/pur_clock/comments",
     {"section_id": "s", "text": "t"}),
    ("post", "/api/pursuits/pur_clock/accept", {}),
    ("post", "/api/pursuits/pur_clock/outcome",
     {"result": "won"}),
    ("post", "/api/pursuits/pur_clock/share",
     {"label": "x", "expires_at": "2026-08-16T09:00:00"}),
    ("post", "/api/orgs", {"name": "Synthetic Org"}),
])
def test_a_client_clock_on_a_mutating_door_is_refused(client, method, path,
                                                      payload):
    r = getattr(client, method)(path, json={**payload, "at": FIXED_AT})
    assert r.status_code == 422, (r.status_code, r.text)
    assert "server stamps the clock" in r.json()["detail"]


def test_the_stamp_is_the_servers_clock(client):
    r = client.post("/api/orgs", json={"name": "Synthetic Org"})
    assert r.status_code == 200, r.text
    assert r.json()["created_at"] == FIXED_AT


def test_a_read_time_staleness_probe_keeps_its_parameter(client):
    r = client.get("/api/kb/cards", params={"at": "2030-01-01T00:00:00"})
    assert r.status_code == 200


def test_the_app_clock_is_movable_for_tests(client):
    client.app.state.clock = lambda: "2026-08-10T09:00:00"
    r = client.post("/api/orgs", json={"name": "Later Org"})
    assert r.json()["created_at"] == "2026-08-10T09:00:00"
    client.app.state.clock = lambda: FIXED_AT


def test_ping_parse_subtracts_naive_and_aware_safely():
    naive = pings._parse("2026-09-02T10:00:00")        # the server's own clock
    aware = pings._parse("2026-09-02T09:00:00Z")       # a Z-suffixed record
    assert naive - aware == timedelta(hours=1)
    offset = pings._parse("2026-09-02T11:00:00+01:00")
    assert offset == pings._parse("2026-09-02T10:00:00")
