"""P27 wave 1 — the door index's `surface` column equals the doors the
shipped shells actually reach (B110).

Every web-route row in docs/graph/doors.md carries a fifth column,
`surface`: `ui` (the workbench shell reaches the path), `guest` (the
share page reaches it), `shell` (the page itself), `api` (reached only
by headless callers — CLI, tests, the pilot host — deliberately). This
test compares the column against the path literals in the static
sources, in both directions, and pins the `api` set CLOSED so a door can
only stay terminal on purpose.

Stated limit: the pin is on PATH SKELETONS, not HTTP methods — `GET` and
`POST …/share` share one literal — and a literal's presence proves the
shell can reach the door, not that a button fires it (there is no
browser harness; behaviour is proven by the routes' own tests)."""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DOORS = REPO / "docs" / "graph" / "doors.md"
STATIC = REPO / "engine" / "web" / "static"
WORKBENCH = ("app.html", "app.js")
GUEST = ("share.html", "share.js")
SURFACES = ("ui", "guest", "shell", "api")

_LITERAL = re.compile(r"(?:/api|/share)(?![\w.-])(?:/[^\s\"'`?]*)?")
_JS_PARAM = re.compile(r"\$\{[^}]*\}")
_DOC_PARAM = re.compile(r"\{[^}]*\}")


def _route_rows():
    """(method, path, surface) for every row under a `method` header."""
    rows, text = [], DOORS.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(text):
        cells = [c.strip() for c in line.strip("|").split("|")]
        if not line.startswith("|") or cells[0] != "method":
            continue
        assert cells[-1] == "surface", f"header without a surface column: {line}"
        for later in text[i + 1:]:
            if not later.startswith("|"):
                break
            cells = [c.strip() for c in later.strip("|").split("|")]
            if all(set(c) <= {"-", " "} for c in cells):
                continue
            rows.append((cells[0], cells[1].strip("`"), cells[-1]))
    assert rows
    return rows


def _doc_skeleton(path):
    return _DOC_PARAM.sub("{}", path)


def _source_skeletons(names):
    out = set()
    for name in names:
        src = (STATIC / name).read_text(encoding="utf-8")
        for lit in _LITERAL.findall(src):
            # a source literal names a parameter as ${expr} or, when the
            # path is built from a template, as {name} — both collapse
            out.add(_DOC_PARAM.sub("{}", _JS_PARAM.sub("{}", lit)).rstrip("/"))
    return out


def test_every_route_row_names_a_known_surface():
    bad = [(m, p, s) for m, p, s in _route_rows() if s not in SURFACES]
    assert not bad, bad


def test_ui_rows_equal_the_workbench_paths():
    doc = {_doc_skeleton(p).rstrip("/") for _, p, s in _route_rows()
           if s == "ui"}
    # the workbench BUILDS a guest URL to hand out (share management); a
    # /share literal there is a display path, not a door the shell calls
    src = {s for s in _source_skeletons(WORKBENCH) if not s.startswith("/share")}
    assert doc - src == set(), f"marked ui, unreached: {sorted(doc - src)}"
    assert src - doc == set(), f"reached, not marked ui: {sorted(src - doc)}"


def test_guest_rows_equal_the_share_page_paths():
    doc = {_doc_skeleton(p).rstrip("/") for _, p, s in _route_rows()
           if s == "guest"}
    if not all((STATIC / n).exists() for n in GUEST):
        assert doc == set(), "guest rows before the guest page exists"
        return
    src = _source_skeletons(GUEST)
    assert doc - src == set(), f"marked guest, unreached: {sorted(doc - src)}"
    assert src - doc == set(), f"reached, not marked guest: {sorted(src - doc)}"


def test_the_shell_row_is_the_page_itself():
    assert {p for _, p, s in _route_rows() if s == "shell"} == {"/"}


# P27 wave 1's acceptance (B93 + B110): the curl doors, share management,
# the waiver, the ping inbox, the guest page, the review-loop doors and
# the effort door are surfaced — frozen here so a later edit cannot
# quietly hand one back to the terminal.
WAVE_1 = {
    ("POST", "/api/pursuits/{pursuit_id}/export"): "ui",
    ("GET", "/api/pursuits/{pursuit_id}/downloads"): "ui",
    ("GET", "/api/pursuits/{pursuit_id}/download/{name:path}"): "ui",
    ("GET", "/api/pursuits/{pursuit_id}/writeback/preview"): "ui",
    ("POST", "/api/pursuits/{pursuit_id}/writeback/confirm"): "ui",
    ("GET", "/api/pursuits/{pursuit_id}/writeback/hand-fill"): "ui",
    ("PUT", "/api/pursuits/{pursuit_id}/writeback/hand-fill"): "ui",
    ("POST", "/api/pursuits/{pursuit_id}/share"): "ui",
    ("GET", "/api/pursuits/{pursuit_id}/share"): "ui",
    ("POST", "/api/pursuits/{pursuit_id}/share/{link_id}/revoke"): "ui",
    ("GET", "/share/{token}"): "guest",
    ("POST", "/share/{token}/comments"): "guest",
    ("POST", "/api/pursuits/{pursuit_id}/waivers"): "ui",
    ("POST", "/api/pursuits/{pursuit_id}/gaps"): "ui",
    ("POST", "/api/pursuits/{pursuit_id}/gaps/{gap_id}/ping"): "ui",
    ("POST", "/api/pursuits/{pursuit_id}/pings/{ping_id}/answer"): "ui",
    ("GET", "/api/pursuits/{pursuit_id}/pings"): "ui",
    ("GET", "/api/pings"): "ui",
    ("DELETE", "/api/pursuits/{pursuit_id}/comments/{cid}"): "ui",
    ("POST", "/api/pursuits/{pursuit_id}/comments/{cid}/include"): "ui",
    ("POST", "/api/pursuits/{pursuit_id}/comments/{cid}/dismiss"): "ui",
    ("POST", "/api/pursuits/{pursuit_id}/events"): "ui",
    ("POST", "/api/pursuits/{pursuit_id}/accept"): "ui",
    ("POST", "/api/pursuits/{pursuit_id}/outcome"): "ui",
    ("POST", "/api/pursuits/{pursuit_id}/effort"): "ui",
}


def test_every_wave_1_door_is_surfaced():
    rows = {(m, p): s for m, p, s in _route_rows()}
    missing = {k: (rows.get(k), v) for k, v in WAVE_1.items() if rows.get(k) != v}
    assert not missing, missing


# The doors that stay headless on purpose — each shrinks this set
# deliberately (wave 2, A5), never by drift.
API_ROWS = frozenset({
    ("GET", "/api/health"),
    ("GET", "/api/pursuits/{pursuit_id}/runs"),
    ("GET", "/api/pursuits/{pursuit_id}/runs/{run_id}"),
    ("GET", "/api/orgs"),
    ("POST", "/api/orgs"),
    ("POST", "/api/orgs/{org_id}/notes"),
    ("GET", "/api/jobs"),
    ("POST", "/api/jobs/{job_id}/cancel"),
    ("GET", "/api/pursuits/{pursuit_id}/revisions"),
    ("GET", "/api/pursuits/{pursuit_id}/revisions/{n}"),
    ("POST", "/api/pursuits/{pursuit_id}/addenda"),
    ("GET", "/api/pursuits/{pursuit_id}/addenda"),
    ("POST", "/api/pursuits/{pursuit_id}/addenda/{aid}/decide"),
    ("GET", "/api/kb/cards/{kb_id}"),
    ("POST", "/api/kb/proposals/merge"),
    ("POST", "/api/kb/import.xlsx"),
    ("POST", "/api/advisor"),
    ("GET", "/api/advisor/cost"),
    ("GET", "/api/advisor/gaps"),
})


def test_the_api_set_is_closed():
    api = {(m, p) for m, p, s in _route_rows() if s == "api"}
    assert api == API_ROWS, (
        f"api rows changed — now terminal: {sorted(api - API_ROWS)}; "
        f"now surfaced: {sorted(API_ROWS - api)}")
