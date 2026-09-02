"""c8 foundation: auth on every mutating route, the serve.lock, pursuit
creation guards, and the offline proof — every route exercised here runs
under a RAISING caller factory (conftest), so a single caller
construction on a read path fails the suite."""

import pytest
from fastapi.testclient import TestClient

from engine.web.auth import DECLARABLE_ROLES
from engine.web.server import create_app
from tests.web.conftest import FIXED_AT, raising_caller, sign_in


# -- auth ----------------------------------------------------------------


def test_mutating_routes_401_without_a_session(offline_app):
    assert offline_app.post(
        "/api/pursuits", json={"pursuit_id": "pur_x"}).status_code == 401
    assert offline_app.put(
        "/api/pursuits/pur_x/inbox/f.xlsx", content=b"x").status_code == 401
    assert offline_app.post(
        "/api/pursuits/pur_x/jobs", json={"kind": "advance"}
    ).status_code == 401
    assert offline_app.post("/api/jobs/job-0001/cancel").status_code == 401
    # P15: the gate_0 decision is an operator's — guests stay out
    assert offline_app.post(
        "/api/pursuits/pur_x/gate0", json={"decision": "approved"}
    ).status_code == 401


def test_reads_stay_open(offline_app):
    assert offline_app.get("/api/pursuits").status_code == 200
    assert offline_app.get("/api/jobs").status_code == 200
    assert offline_app.get("/api/health").status_code == 200
    assert offline_app.get("/api/session").json() == {
        "operator": None, "role": None, "roles": list(DECLARABLE_ROLES)}


def test_declared_session_flow(offline_app):
    name = sign_in(offline_app, "Sam Lead")
    assert name == "Sam Lead"
    assert offline_app.get("/api/session").json() == {
        "operator": "Sam Lead", "role": "pursuit_lead",
        "roles": list(DECLARABLE_ROLES)}
    out = offline_app.post("/api/pursuits",
                           json={"pursuit_id": "pur_alpha"}).json()
    assert out == {"pursuit_id": "pur_alpha", "created_by": "Sam Lead"}


def test_header_mode_is_the_sso_seam(tmp_path):
    cfg = tmp_path / "web.yaml"
    cfg.write_text("auth:\n  mode: header\n  header_name: X-Auth-User\n",
                   encoding="utf-8")
    app = create_app(tmp_path / "ws", make_caller=raising_caller,
                     auth_config=cfg, now=lambda: FIXED_AT)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        # identity comes from the proxy header
        r = client.post("/api/pursuits", json={"pursuit_id": "pur_h"},
                        headers={"X-Auth-User": "Proxy Person"})
        assert r.json()["created_by"] == "Proxy Person"
        # missing header names the expectation
        r = client.post("/api/pursuits", json={"pursuit_id": "pur_h2"})
        assert r.status_code == 401
        assert "X-Auth-User" in r.json()["detail"]
        # the declared door is closed in header mode
        r = client.post("/api/session", json={"name": "anyone"})
        assert r.status_code == 400


# -- serve.lock ----------------------------------------------------------


def test_second_server_on_one_workspace_refuses(tmp_path):
    app = create_app(tmp_path / "ws", make_caller=raising_caller)
    with pytest.raises(RuntimeError, match="one server per workspace"):
        create_app(tmp_path / "ws", make_caller=raising_caller)
    del app


# -- pursuit creation guards --------------------------------------------


def test_pursuit_id_shape_reserved_and_duplicates(offline_app):
    sign_in(offline_app)
    bad = offline_app.post("/api/pursuits", json={"pursuit_id": "nope!"})
    assert bad.status_code == 422
    reserved = offline_app.post("/api/pursuits",
                                json={"pursuit_id": "pur_support"})
    assert reserved.status_code == 409
    assert "unmixable" in reserved.json()["detail"]
    assert offline_app.post(
        "/api/pursuits", json={"pursuit_id": "pur_dup"}).status_code == 200
    assert offline_app.post(
        "/api/pursuits", json={"pursuit_id": "pur_dup"}).status_code == 409


def test_upload_guards(offline_app):
    sign_in(offline_app)
    offline_app.post("/api/pursuits", json={"pursuit_id": "pur_up"})
    empty = offline_app.put("/api/pursuits/pur_up/inbox/f.xlsx", content=b"")
    assert empty.status_code == 400
    traversal = offline_app.put(
        "/api/pursuits/pur_up/inbox/%2e%2e%2fevil.txt", content=b"x")
    assert traversal.status_code in (404, 422)  # never a stored file
    ok = offline_app.put("/api/pursuits/pur_up/inbox/pkg.xlsx",
                         content=b"bytes")
    assert ok.json()["stored"] == "inbox/pkg.xlsx"


def test_detail_404_never_creates_a_phantom_pursuit(offline_app, tmp_path):
    # the v1 trap: PursuitDir.__init__ mkdirs — a GET must not
    assert offline_app.get("/api/pursuits/pur_ghost").status_code == 404
    workspace = tmp_path / "ws"
    assert not (workspace / "pur_ghost").exists()
    board = offline_app.get("/api/pursuits").json()
    assert all(row["pursuit_id"] != "pur_ghost" for row in board)


def test_shell_is_neutral_and_self_contained(offline_app):
    page = offline_app.get("/").text
    assert "RFP Engine" in page  # the neutral name (D31, pending J6)
    assert "http" not in page.split("</head>")[0].replace(
        "http-equiv", "")  # no CDN/external fetch in the head
    js = offline_app.get("/static/app.js").text
    assert "esc(" in js  # the XSS discipline is present, pinned



def test_every_door_checks_the_pursuit_id_shape(offline_app):
    """P25 item 4 (P2-17): the id regex guards every door, not only
    creation — a malformed id is 422 and creates nothing."""
    client = offline_app
    ws = client.app.state.workspace
    before = sorted(p.name for p in ws.parent.iterdir())
    for bad in ("not-an-id", "pur_UPPER", "pur_a b"):
        r = client.get(f"/api/pursuits/{bad}/downloads")
        assert r.status_code == 422, (bad, r.status_code)
    # a traversal segment is normalized away by the client or refused by
    # the shape check — either way nothing is created below
    r = client.get("/api/pursuits/%2E%2E/downloads")
    assert r.status_code in (404, 422)
    assert sorted(p.name for p in ws.parent.iterdir()) == before
    assert not (ws.parent / "drafts").exists()


def test_download_door_refuses_a_bundle_path_outside_the_pursuit(offline_app):
    """P25 item 4 (P2-16): the download door trusts the bundle RECORD for
    the path, so it re-checks containment before serving."""
    import json
    client = offline_app
    sign_in(client, "Dora Downloader")
    client.post("/api/pursuits", json={"pursuit_id": "pur_dl"})
    root = client.app.state.workspace / "pur_dl"
    (root / "exports").mkdir(parents=True, exist_ok=True)
    (root / "exports" / "submission-bundle.json").write_text(json.dumps({
        "deliverables": [{"name": "x.docx", "status": "produced",
                          "path": "../../escape.docx"}]}))
    r = client.get("/api/pursuits/pur_dl/download/x.docx")
    assert r.status_code == 403
