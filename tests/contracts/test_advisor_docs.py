"""docs/advisor/*.md ship in the public cut and had no drift test — the
structural reason the revision-history claim rotted (P0-10, P26a Group D).
Two pins, the operator-guide discipline extended: every backticked
`METHOD /path` resolves to a door-index row, and every bold phrase is
on-screen text present in the web app's source."""

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
ADVISOR = REPO / "docs" / "advisor"
DOORS = REPO / "docs" / "graph" / "doors.md"
DOCS = sorted(ADVISOR.glob("*.md"))
_ROUTE_RX = re.compile(r"`(GET|POST|PUT|DELETE|PATCH|HEAD) (/[^`]*)`")


def _door_rows():
    rows = set()
    for line in DOORS.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) >= 2 and cells[0] in (
                "GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"):
            rows.add((cells[0], cells[1].strip("`")))
    return rows


def test_the_advisor_docs_exist():
    assert len(DOCS) >= 6, [p.name for p in DOCS]


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_route_references_resolve_to_door_rows(doc):
    rows = _door_rows()
    for method, path in _ROUTE_RX.findall(doc.read_text(encoding="utf-8")):
        assert (method, path) in rows, (
            f"docs/advisor/{doc.name} cites `{method} {path}` but the door "
            "index carries no such row")


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_bold_spans_are_on_screen_text(doc):
    static = REPO / "engine" / "web" / "static"
    ui = "".join((static / n).read_text() for n in
                 ("app.html", "app.js", "share.html", "share.js"))
    text = doc.read_text(encoding="utf-8")
    spans = text.split("**")[1::2]  # odd segments are the bold contents
    wrapped = [s for s in spans if "\n" in s]
    assert not wrapped, f"a bold span wraps across a line break: {wrapped}"
    missing = sorted({s for s in spans if s not in ui})
    assert not missing, (
        f"docs/advisor/{doc.name}: bold is reserved for on-screen text, "
        f"and these spans appear nowhere in the UI source: {missing}")


def test_no_advisor_doc_claims_a_surface_the_workbench_lacks():
    """The sentence that drifted, pinned by its absence: the revision
    doors exist (GET …/revisions, …/revisions/{n}); the workbench renders
    no history panel yet (P27 wave 2 owns it)."""
    text = (ADVISOR / "review-and-revision.md").read_text(encoding="utf-8")
    assert "revision history shows" not in text.lower()
    assert "GET /api/pursuits/{pursuit_id}/revisions" in text
