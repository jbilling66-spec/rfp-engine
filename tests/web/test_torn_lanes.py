"""P2-57 (P29b b2): B106 §1 said the events lane and share links fold
through `read_jsonl`; neither did. A torn FINAL line in `events.jsonl`
500'd every feedback door and the revise round; a torn tail in ONE
pursuit's `share/links.jsonl` 500'd every guest route for ALL pursuits
plus that pursuit's revoke. Now: both lanes read through the one
tolerant reader, repair the tail under their own lock at the next
append, and name themselves on the board row; a corrupt links lane is
scoped to its pursuit. The pings lane surfaces the report it used to
discard."""

import json

import pytest
from fastapi.testclient import TestClient

from engine.contracts import ContractError
from engine.web.events import EventsLane
from engine.web.pings import PingLane
from engine.web.share import ShareLane
from engine.web.server import create_app
from engine.web.state import board
from engine.workspace import PursuitDir
from tests.validation.fixtures.validations import run_validation_package
from tests.web.conftest import FIXED_AT, raising_caller, sign_in

EXPIRES = "2026-08-16T09:00:00"
FRAGMENT = b'{"event_id": "evt_9'  # a writer caught mid-append


@pytest.fixture(scope="module")
def torn(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("web-torn")
    pursuit, report, _ = run_validation_package(tmp)
    assert report.status == "complete"
    app = create_app(tmp, make_caller=raising_caller, now=lambda: FIXED_AT)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        sign_in(client, "Tess Tearer")
        yield client, pursuit, tmp


def _tear(path, fragment=FRAGMENT):
    data = path.read_bytes()
    assert data.endswith(b"\n")
    path.write_bytes(data + fragment)


def _lines(path):
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()]


def _row(ws, pid):
    return next(r for r in board(ws) if r["pursuit_id"] == pid)


# -- the events lane ----------------------------------------------------------


def test_a_torn_events_tail_is_read_named_and_repaired_at_the_next_append(
        torn):
    client, pursuit, ws = torn
    pid = pursuit.pursuit_id
    assert client.post(f"/api/pursuits/{pid}/outcome", json={
        "result": "won"}).status_code == 200
    path = pursuit.root / "events" / "events.jsonl"
    _tear(path)
    # every read door tolerates the tail and the lane reports it
    assert client.get(f"/api/pursuits/{pid}/comments").status_code == 200
    lane = EventsLane(pursuit)
    assert lane.read() and lane.torn and "torn final line" in lane.torn
    assert lane.finalized_by_cid() == {}  # the revise round's read
    assert _row(ws, pid)["torn"] == [lane.torn]
    assert "corrupt" not in _row(ws, pid)
    # the next append repairs under the lock: the fragment is gone, every
    # line is a record, and the lane no longer reports a tear
    assert client.post(f"/api/pursuits/{pid}/outcome", json={
        "result": "won"}).status_code == 200
    assert not path.read_bytes().rstrip(b"\n").endswith(FRAGMENT.rstrip())
    assert len(_lines(path)) == 2
    lane.read()
    assert lane.torn is None
    assert "torn" not in _row(ws, pid)


def test_a_torn_earlier_events_line_is_corruption_named_on_the_row(
        tmp_path):
    pursuit = PursuitDir(tmp_path, "pur_evc")
    (pursuit.root / "inbox").mkdir(parents=True, exist_ok=True)
    path = pursuit.root / "events" / "events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'{"event_id": "evt_0001", "kind": "outcome"}\n'
                     b'{"event_id": "evt_00\n'
                     b'{"event_id": "evt_0003", "kind": "outcome"}\n')
    with pytest.raises(ContractError, match="line 2 is not a JSON record"):
        EventsLane(pursuit).read()
    row = _row(tmp_path, "pur_evc")
    assert row["stage"] == "corrupt"
    assert any(c.startswith("events/events.jsonl:") for c in row["corrupt"])


# -- share links --------------------------------------------------------------


def test_a_torn_links_lane_is_scoped_to_its_pursuit(torn):
    client, pursuit, ws = torn
    pid = pursuit.pursuit_id
    link = client.post(f"/api/pursuits/{pid}/share", json={
        "label": "counsel", "expires_at": EXPIRES}).json()
    # a second pursuit with its own link, then its lane torn
    assert client.post("/api/pursuits",
                       json={"pursuit_id": "pur_other"}).status_code == 200
    other = client.post("/api/pursuits/pur_other/share", json={
        "label": "other", "expires_at": EXPIRES}).json()
    other_path = ws / "pur_other" / "share" / "links.jsonl"
    _tear(other_path, b'{"link_id": "sl_9')
    # the first pursuit's guest is unaffected; the torn lane is named
    assert client.get(f"/share/{link['token']}").status_code == 200
    assert _row(ws, "pur_other")["torn"]
    other_lane = ShareLane(PursuitDir(ws, "pur_other"))
    assert other_lane.links() and other_lane.torn
    # the torn pursuit's own revoke works and repairs the tail
    r = client.post(f"/api/pursuits/pur_other/share/{other['link_id']}/revoke",
                    json={})
    assert r.status_code == 200
    assert all(_lines(other_path))
    other_lane.links()
    assert other_lane.torn is None
    assert client.get(f"/share/{other['token']}").status_code == 410


def test_a_corrupt_links_lane_404s_only_its_own_guests(torn):
    client, pursuit, ws = torn
    pid = pursuit.pursuit_id
    link = client.get(f"/api/pursuits/{pid}/share").json()[0]
    assert client.post("/api/pursuits",
                       json={"pursuit_id": "pur_corrupt"}).status_code == 200
    bad = client.post("/api/pursuits/pur_corrupt/share", json={
        "label": "bad", "expires_at": EXPIRES}).json()
    bad_path = ws / "pur_corrupt" / "share" / "links.jsonl"
    bad_path.write_bytes(b'{"link_id": "sl_0\n' + bad_path.read_bytes())
    assert client.get(f"/share/{link['token']}").status_code == 200
    assert client.get(f"/share/{bad['token']}").status_code == 404
    row = _row(ws, "pur_corrupt")
    assert row["stage"] == "corrupt"
    assert any(c.startswith("share/links.jsonl:") for c in row["corrupt"])


# -- pings --------------------------------------------------------------------


def test_the_pings_lane_reports_the_tear_it_used_to_discard(tmp_path):
    pursuit = PursuitDir(tmp_path, "pur_png")
    lane = PingLane(pursuit)
    lane.path.parent.mkdir(parents=True, exist_ok=True)
    lane.path.write_bytes(b'{"ping_id": "png_0001", "gap_id": "g1"}\n'
                          b'{"ping_id": "png_00')
    assert list(lane._folded()) == ["png_0001"]
    assert lane.torn and "torn final line" in lane.torn
