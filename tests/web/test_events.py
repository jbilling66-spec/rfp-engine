"""The events lane (B37/D5/D11/D12/D13/D30) over a REAL validated
pursuit (the P8 fixture chain), under a RAISING caller factory — none of
these routes may ever ask for a model. Carries the frozen acceptance
clause: effort confirmed+passive BOTH retained."""

import json

import pytest
from fastapi.testclient import TestClient

from engine.contracts import ContractError
from engine.web.events import EventsLane
from engine.web.server import create_app
from engine.workspace import PursuitDir
from tests.validation.fixtures.validations import (
    make_validation_script,
    run_validation_package,
)
from tests.web.conftest import FIXED_AT, raising_caller, sign_in



@pytest.fixture(scope="module")
def reviewed(tmp_path_factory):
    """A clean validated pursuit (packaging unblocked) served by the app."""
    tmp = tmp_path_factory.mktemp("web-events")
    pursuit, report, _ = run_validation_package(tmp)
    assert report.status == "complete"
    app = create_app(tmp, make_caller=raising_caller, now=lambda: FIXED_AT)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        sign_in(client)
        yield client, pursuit


def _events(pursuit):
    path = pursuit.root / "events" / "events.jsonl"
    if not path.exists():
        return []
    return [json.loads(l) for l in
            path.read_text(encoding="utf-8").splitlines()]


# -- effort (the frozen acceptance clause) --------------------------------


def test_confirmed_event_retains_passive_figure(reviewed):
    client, pursuit = reviewed
    pid = pursuit.pursuit_id
    passive = client.post(f"/api/pursuits/{pid}/effort", json={
        "measurement": "passive", "active_ms": 462_000,
        "scope": "section"})
    assert passive.status_code == 200
    confirmed = client.post(f"/api/pursuits/{pid}/effort", json={
        "measurement": "confirmed", "active_ms": 462_000,
        "confirmed_minutes": 9, "scope": "gate", "gate": "review_loop",
        })
    assert confirmed.status_code == 200
    sessions = [e for e in _events(pursuit) if e["kind"] == "review_session"]
    kinds = [s["effort"]["measurement"] for s in sessions]
    assert "passive" in kinds and "confirmed" in kinds
    conf = next(s for s in sessions
                if s["effort"]["measurement"] == "confirmed")
    # BOTH figures on ONE event — the acceptance carrier (D13/G5)
    assert conf["effort"]["active_ms"] == 462_000
    assert conf["effort"]["confirmed_minutes"] == 9
    # and the separate passive event is retained too
    assert any(s["effort"] == {"active_ms": 462_000,
                               "measurement": "passive",
                               "scope": "section"} for s in sessions)


def test_effort_guards(reviewed):
    client, pursuit = reviewed
    pid = pursuit.pursuit_id
    no_passive = client.post(f"/api/pursuits/{pid}/effort", json={
        "measurement": "confirmed", "confirmed_minutes": 9,
        "scope": "gate", "gate": "gate_1"})
    assert no_passive.status_code == 422
    assert "BOTH figures" in no_passive.json()["detail"]
    assert client.post(f"/api/pursuits/{pid}/effort", json={
        "measurement": "passive", "scope": "section"}
    ).status_code == 422
    # schema allOf non-vacuity: a review_session with NO effort block is
    # structurally unwritable at the lane
    lane = EventsLane(pursuit)
    with pytest.raises(ContractError):
        lane.append("review_session", at=FIXED_AT, actor="x",
                    actor_role="pursuit_lead")


# -- outcome (D30) --------------------------------------------------------


def test_outcome_corrections_are_append_only_last_wins(reviewed):
    client, pursuit = reviewed
    pid = pursuit.pursuit_id
    client.post(f"/api/pursuits/{pid}/outcome",
                json={"result": "shortlisted"})
    client.post(f"/api/pursuits/{pid}/outcome",
                json={"result": "won",
                      "buyer_feedback": "strong transition story"})
    outcomes = [e for e in _events(pursuit) if e["kind"] == "outcome"]
    assert len(outcomes) == 2  # the record keeps both
    assert EventsLane(pursuit).latest_outcome()["outcome"]["result"] == "won"


# -- comments / pending (D5, D11) -----------------------------------------


def test_comment_pends_and_flips_draft_status_on_live_plan_only(reviewed):
    client, pursuit = reviewed
    pid = pursuit.pursuit_id
    frozen_before = (pursuit.root / "plan.frozen.json").read_bytes()
    section_id = json.loads(
        (pursuit.root / "plan.json").read_text())["sections"][0]["section_id"]
    r = client.post(f"/api/pursuits/{pid}/comments", json={
        "kind": "comment", "section_id": section_id,
        "text": "Tighten the second paragraph."})
    assert r.status_code == 200
    entry = r.json()
    assert entry["provenance"] == "internal"
    listed = client.get(f"/api/pursuits/{pid}/comments").json()
    assert [p["cid"] for p in listed["pending"]] == [entry["cid"]]
    assert listed["events"] == []  # pends until a round, never an event yet
    plan = json.loads((pursuit.root / "plan.json").read_text())
    section = next(s for s in plan["sections"]
                   if s["section_id"] == section_id)
    assert section["draft_status"] == "in_review"
    # the frozen copy never moved (freeze integrity)
    assert (pursuit.root / "plan.frozen.json").read_bytes() == frozen_before
    # delete restores nothing but removes the pending entry
    assert client.delete(
        f"/api/pursuits/{pid}/comments/{entry['cid']}").status_code == 200
    assert client.get(
        f"/api/pursuits/{pid}/comments").json()["pending"] == []


def test_comment_guards(reviewed):
    client, pursuit = reviewed
    pid = pursuit.pursuit_id
    assert client.post(f"/api/pursuits/{pid}/comments", json={
        "kind": "comment", "section_id": "nope", "text": "x"}
    ).status_code == 400
    section_id = json.loads(
        (pursuit.root / "plan.json").read_text())["sections"][0]["section_id"]
    no_diff = client.post(f"/api/pursuits/{pid}/comments", json={
        "kind": "edit", "section_id": section_id})
    assert no_diff.status_code == 422
    assert "before AND after" in no_diff.json()["detail"]
    # P27 (M-9): a payload role — valid or not — is refused; the session
    # names the role and the detail says so
    bad_role = client.post(f"/api/pursuits/{pid}/comments", json={
        "kind": "comment", "section_id": section_id, "text": "x",
        "actor_role": "ceo"})
    assert bad_role.status_code == 422
    assert "session names the role" in bad_role.json()["detail"]


# -- accept (D12, D11 final) ----------------------------------------------


def test_accept_is_pursuit_scoped_and_stamps_final(reviewed):
    client, pursuit = reviewed
    pid = pursuit.pursuit_id
    r = client.post(f"/api/pursuits/{pid}/accept", json={})
    assert r.status_code == 200
    event = r.json()
    assert event["kind"] == "accept"
    assert "section_id" not in event  # pursuit scope — D12
    plan = json.loads((pursuit.root / "plan.json").read_text())
    stamped = [s for s in plan["sections"] if "draft_status" in s]
    assert stamped and all(s["draft_status"] == "final" for s in stamped)


def test_accept_refuses_blocked_packaging(tmp_path):
    pursuit, report, _ = run_validation_package(
        tmp_path, script=make_validation_script(plant_unsupported=True))
    app = create_app(tmp_path, make_caller=raising_caller,
                     now=lambda: FIXED_AT)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        sign_in(client)
        r = client.post(f"/api/pursuits/{pursuit.pursuit_id}/accept",
                        json={})
        assert r.status_code == 409
        assert "BLOCKED" in r.json()["detail"]
        assert _events(pursuit) == []  # a refused accept leaves no event


def test_accept_requires_an_annotated_draft(offline_app):
    sign_in(offline_app)
    offline_app.post("/api/pursuits", json={"pursuit_id": "pur_early"})
    r = offline_app.post("/api/pursuits/pur_early/accept", json={})
    assert r.status_code == 409
    assert "nothing to accept" in r.json()["detail"]



def test_event_ids_mint_from_the_lane_max_under_concurrency(tmp_path):
    """P25 item 3 (P1-20): ids are max(existing)+1 — a gap in the lane is
    never refilled — and forty concurrent appends from two threads mint
    forty DISTINCT ids into the append-only record."""
    import json
    import threading

    from engine.web.events import EventsLane
    from engine.workspace import PursuitDir
    pursuit = PursuitDir(tmp_path, "pur_ev")
    lane = EventsLane(pursuit)
    lane.events_path.parent.mkdir(parents=True, exist_ok=True)
    lane.events_path.write_text(
        json.dumps({"event_id": "evt_0001", "kind": "accept"}) + "\n"
        + json.dumps({"event_id": "evt_0003", "kind": "accept"}) + "\n")
    first = lane.append("accept", at="2026-08-09T09:00:00", actor="a",
                        actor_role="pursuit_lead")
    assert first["event_id"] == "evt_0004"  # never evt_0003 again

    def burst():
        for _ in range(20):
            EventsLane(pursuit).append("accept", at="2026-08-09T09:00:00",
                                       actor="t", actor_role="pursuit_lead")

    threads = [threading.Thread(target=burst) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    ids = [e["event_id"] for e in lane.read()]
    assert len(ids) == 43 and len(set(ids)) == 43


def test_mutating_event_and_share_routes_serialize_under_the_guard():
    """Structural pin for P1-20/P1-22: the four routes that used to
    append outside the job lane take `_mutate` — the behavioural half
    (serialized ids) is the lane test above."""
    import inspect

    import engine.web.server as server
    src = inspect.getsource(server)
    for func in ("add_event", "record_outcome", "record_effort",
                 "create_share", "revoke_share"):
        start = src.index(f"    def {func}(")
        end = src.index("\n    @app.", start)
        assert "with _mutate(pursuit_id):" in src[start:end], func
