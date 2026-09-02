"""P25 item 4 (P0-7): host validation, the baseline security headers on
EVERY response, no-store on the API, and the cross-site write guard."""

import pytest
from fastapi.testclient import TestClient

from engine.web.headers import SECURITY_HEADERS
from engine.web.server import create_app
from tests.web.conftest import raising_caller, sign_in

FROZEN_HEADER_SET = frozenset(SECURITY_HEADERS)


def test_every_response_carries_the_baseline_headers(offline_app):
    client = offline_app
    client.post("/api/pursuits", json={"pursuit_id": "pur_h"})
    for path, expect in (("/", 200), ("/static/app.js", 200),
                         ("/api/health", 200),
                         ("/api/pursuits/pur_nope", 404),
                         ("/api/pursuits/not-an-id/downloads", 422)):
        r = client.get(path)
        assert r.status_code == expect, (path, r.status_code)
        for name, value in SECURITY_HEADERS.items():
            assert r.headers.get(name) == value, (path, name)
        if path.startswith("/api/"):
            assert r.headers.get("cache-control") == "no-store"
    # the set is frozen: a dropped header reds this line, not a reader
    assert FROZEN_HEADER_SET == {
        "content-security-policy", "x-content-type-options",
        "x-frame-options", "referrer-policy",
        "cross-origin-opener-policy", "cross-origin-resource-policy"}


def test_untrusted_host_is_refused_even_on_loopback(offline_app):
    client = offline_app
    r = client.get("/api/health", headers={"host": "evil.example"})
    assert r.status_code == 400
    assert r.headers.get("x-frame-options") == "DENY"  # headers outermost
    sign_in(client, "Host Tester")
    r = client.put("/api/pursuits/pur_x/inbox/a.md", content=b"x",
                   headers={"host": "evil.example"})
    assert r.status_code == 400
    for host in ("127.0.0.1", "127.0.0.1:8400", "localhost", "localhost:8400"):
        assert client.get("/api/health", headers={"host": host}).status_code == 200


def test_allowed_hosts_is_the_operator_seam(tmp_path):
    app = create_app(tmp_path / "ws", make_caller=raising_caller,
                     allowed_hosts=("proxy.internal",))
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.get("/api/health").status_code == 400
        assert client.get("/api/health",
                          headers={"host": "proxy.internal"}).status_code == 200


def test_cross_site_writes_are_refused_reads_pass(offline_app):
    client = offline_app
    sign_in(client, "Site Tester")
    client.post("/api/pursuits", json={"pursuit_id": "pur_s"})
    r = client.put("/api/pursuits/pur_s/inbox/a.md", content=b"x",
                   headers={"sec-fetch-site": "cross-site"})
    assert r.status_code == 403 and "cross-site" in r.json()["detail"]
    assert not (client.app.state.workspace / "pur_s" / "inbox" / "a.md").exists()
    r = client.get("/api/pursuits/pur_s", headers={"sec-fetch-site": "cross-site"})
    assert r.status_code == 200  # reads are unreadable cross-origin anyway
    for site in ("same-origin", "none"):
        r = client.put("/api/pursuits/pur_s/inbox/b.md", content=b"y",
                       headers={"sec-fetch-site": site})
        assert r.status_code == 200, (site, r.text)
