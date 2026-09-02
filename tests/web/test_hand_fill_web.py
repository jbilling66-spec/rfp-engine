"""The hand-completion door over HTTP (P26a item 1, P1-27): the PUT
validates against the template's own slots with typed 422s, stamps the
session identity and the server clock (a client clock is ignored —
P0-11's rule), merges last-write-wins, and the GET reads back the owed
catalogue that shrinks as values land."""

import hashlib

import pytest
from fastapi.testclient import TestClient

from engine.planning.plan import REFERENCE_DEFAULT
from engine.structure import merge_parsed, parse_default_template
from engine.web.server import create_app
from engine.workspace import PursuitDir
from tests.helpers import plant_freeze
from tests.web.conftest import FIXED_AT, raising_caller, sign_in

META = {"prepared_for_client": "Synthetic Buyer Co", "rfp_title": "Synthetic RFP",
        "rfp_solicitation_number": "RFP-0001", "submitted_by": "The Firm",
        "date_of_submission": "2026-09-30", "primary_contact": "Pat Lead",
        "due_date_method": "2026-10-01, portal"}


@pytest.fixture(scope="module")
def hand_client(tmp_path_factory):
    ws = tmp_path_factory.mktemp("web-hand") / "ws"
    app = create_app(ws, make_caller=raising_caller, now=lambda: FIXED_AT)
    client = TestClient(app, base_url="http://127.0.0.1")
    client.__enter__()
    sign_in(client, "Hana Hand")
    client.post("/api/pursuits", json={"pursuit_id": "pur_hand"})
    pursuit = PursuitDir(ws, "pur_hand")
    parsed = parse_default_template(REFERENCE_DEFAULT)
    container = {"pursuit_id": "pur_hand", **merge_parsed([parsed])}
    pursuit.write_artifact("target_slots", container, name="slots.json")
    pursuit.checkpoint("path_b_outline", {
        "reference_sha256": hashlib.sha256(
            REFERENCE_DEFAULT.read_bytes()).hexdigest()})
    plant_freeze(pursuit, "pursuit_plan", {
        "pursuit_id": "pur_hand", "path": "B_free_flow",
        "slots_ref": "slots.json", "status": "approved",
        "sections": [{"section_id": "sec-exec",
                      "slot_ids": ["s-h02-hdr", "s-h02"]}]})
    # a buyer-form pursuit for the lane refusal
    client.post("/api/pursuits", json={"pursuit_id": "pur_buyer"})
    buyer = PursuitDir(ws, "pur_buyer")
    (buyer.root / "slots.json").write_text('{"source_mode": "client_provided"}')
    plant_freeze(buyer, "pursuit_plan", {
        "pursuit_id": "pur_buyer", "path": "A_structured",
        "slots_ref": "slots.json", "status": "approved", "sections": []})
    yield client, ws
    client.__exit__(None, None, None)


def test_the_catalogue_reads_before_any_value_exists(hand_client):
    client, _ = hand_client
    body = client.get("/api/pursuits/pur_hand/writeback/hand-fill").json()
    assert body["record"] is None
    assert {s["slot_id"]: s["status"] for s in body["slots"]} == {
        "s-front-meta": "owed", "s-h10": "owed", "s-h11": "owed",
        "s-h12-1": "owed"}


@pytest.mark.parametrize("payload, code, match", [
    ({"values": "x"}, 422, "values must be an object"),
    ({"values": {"s-h02": "prose"}}, 422, "drafted by the engine"),
    ({"values": {"s-h11": [{"fee": "ten"}]}}, 422, "must parse as a number"),
    ({"values": {"s-h12-1": "bad\x0bchar"}}, 422, "control character"),
])
def test_put_refuses_typed(hand_client, payload, code, match):
    client, _ = hand_client
    r = client.put("/api/pursuits/pur_hand/writeback/hand-fill", json=payload)
    assert r.status_code == code, r.text
    assert match in r.json()["detail"]


def test_put_stamps_the_session_and_the_server_clock_and_merges(hand_client):
    client, _ = hand_client
    refused = client.put("/api/pursuits/pur_hand/writeback/hand-fill", json={
        "values": {"s-h12-1": "x"}, "at": "2001-01-01T00:00:00Z"})
    assert refused.status_code == 422  # P0-11: the server stamps the clock
    r = client.put("/api/pursuits/pur_hand/writeback/hand-fill", json={
        "values": {"s-front-meta": META,
                   "s-h12-1": "Net 30 from invoice"}, "entered_by": "Mallory"})
    assert r.status_code == 200, r.text
    record = r.json()["record"]
    assert record["entered_by"] == "Hana Hand"     # the session, never the payload
    assert record["at"] == FIXED_AT                 # the server clock
    statuses = {s["slot_id"]: s["status"] for s in r.json()["slots"]}
    assert statuses["s-front-meta"] == "filled"
    assert statuses["s-h12-1"] == "filled"
    assert statuses["s-h11"] == "owed"

    r = client.put("/api/pursuits/pur_hand/writeback/hand-fill", json={
        "values": {"s-h11": [{"milestone": "Kickoff", "fee": "$1,000",
                              "duration_weeks": "2"}],
                   "s-h12-1": ""}})
    assert r.status_code == 200, r.text
    values = r.json()["record"]["values"]
    assert values["s-front-meta"] == META            # kept from the first write
    assert "s-h12-1" not in values                   # cleared by the empty value
    assert values["s-h11"][0]["fee"] == "$1,000"
    body = client.get("/api/pursuits/pur_hand/writeback/hand-fill").json()
    assert {s["slot_id"]: s["status"] for s in body["slots"]} == {
        "s-front-meta": "filled", "s-h10": "owed", "s-h11": "filled",
        "s-h12-1": "owed"}


def test_a_buyer_form_pursuit_refuses_the_lane(hand_client):
    client, _ = hand_client
    r = client.put("/api/pursuits/pur_buyer/writeback/hand-fill",
                   json={"values": {"s-h12-1": "x"}})
    assert r.status_code == 409
    assert "firm_default lane" in r.json()["detail"]


def test_put_requires_an_operator(hand_client):
    client, ws = hand_client
    anon = TestClient(client.app, base_url="http://127.0.0.1")
    r = anon.put("/api/pursuits/pur_hand/writeback/hand-fill",
                 json={"values": {"s-h12-1": "x"}})
    assert r.status_code == 401
