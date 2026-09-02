"""P27 wave 1: a guest share link renders a PAGE, never raw JSON.

Content negotiation on the one URL: a browser (Accept: text/html) gets
the static guest shell, served without resolving the token — so the
access log gains nothing until the page's own JSON fetch, which is the
one logged view and carries the 404/410 a dead link earns; every API
caller (TestClient's default Accept, curl) keeps the JSON model, so the
existing share tests hold unchanged. The shell is self-contained and
escapes every interpolation; the guest lane is no-store like the API."""

from fastapi.testclient import TestClient

from engine.web.headers import SECURITY_HEADERS
from engine.web.server import create_app
from tests.validation.fixtures.validations import run_validation_package
from tests.web.conftest import FIXED_AT, raising_caller, sign_in

EXPIRES = "2026-08-16T09:00:00"
HTML = {"Accept": "text/html,application/xhtml+xml,*/*;q=0.8"}
JSON = {"Accept": "application/json"}


def _shared(tmp_path):
    pursuit, report, _ = run_validation_package(tmp_path)
    assert report.status == "complete"
    app = create_app(tmp_path, make_caller=raising_caller,
                     now=lambda: FIXED_AT)
    client = TestClient(app, base_url="http://127.0.0.1")
    client.__enter__()
    sign_in(client, "Skye Sharer")
    link = client.post(f"/api/pursuits/{pursuit.pursuit_id}/share", json={
        "label": "buyer-side counsel", "expires_at": EXPIRES}).json()
    return client, pursuit, link


def _access_lines(pursuit):
    path = pursuit.root / "share" / "access.jsonl"
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


def test_a_browser_gets_the_page_and_an_api_caller_the_model(tmp_path):
    client, pursuit, link = _shared(tmp_path)
    guest = TestClient(client.app, base_url="http://127.0.0.1")
    page = guest.get(f"/share/{link['token']}", headers=HTML)
    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    body = page.text
    assert "/static/share.js" in body and "Send comment" in body
    assert link["token"] not in body            # the shell is static
    assert "<script>" not in body and "onclick=" not in body  # CSP-clean
    model = guest.get(f"/share/{link['token']}", headers=JSON).json()
    assert model["share"]["link_id"] == link["link_id"]
    assert "sections" in model
    default = guest.get(f"/share/{link['token']}")  # Accept */* — JSON
    assert default.headers["content-type"].startswith("application/json")
    assert default.json()["share"]["link_id"] == link["link_id"]


def test_the_shell_never_touches_the_access_log(tmp_path):
    """One view = one access line, and it is the JSON fetch's."""
    client, pursuit, link = _shared(tmp_path)
    guest = TestClient(client.app, base_url="http://127.0.0.1")
    before = _access_lines(pursuit)
    guest.get(f"/share/{link['token']}", headers=HTML)
    assert _access_lines(pursuit) == before
    guest.get(f"/share/{link['token']}", headers=JSON)
    after = _access_lines(pursuit)
    assert len(after) == len(before) + 1
    assert '"action": "view"' in after[-1] and '"granted": true' in after[-1]
    # a dead token: the shell still serves (static), the fetch says why
    dead = guest.get("/share/not-a-token", headers=HTML)
    assert dead.status_code == 200
    assert _access_lines(pursuit) == after
    assert guest.get("/share/not-a-token", headers=JSON).status_code == 404


def test_the_guest_lane_carries_the_baseline_headers_and_no_store(tmp_path):
    client, pursuit, link = _shared(tmp_path)
    guest = TestClient(client.app, base_url="http://127.0.0.1")
    for headers in (HTML, JSON):
        r = guest.get(f"/share/{link['token']}", headers=headers)
        for name, value in SECURITY_HEADERS.items():
            assert r.headers.get(name) == value, name
        assert r.headers.get("cache-control") == "no-store"


def test_the_guest_page_is_self_contained_and_escapes():
    from pathlib import Path
    static = Path(__file__).resolve().parents[2] / "engine" / "web" / "static"
    html = (static / "share.html").read_text(encoding="utf-8")
    js = (static / "share.js").read_text(encoding="utf-8")
    assert "http" not in html.split("</head>")[0].replace("http-equiv", "")
    assert "esc(" in js and '"Accept": "application/json"' in js
    assert "/api/" not in js                      # guests have one door
    assert "display_name" in js and "section_id" in js and "/comments" in js
    assert "sessionStorage" in js and "catch" in js  # storage may be absent
