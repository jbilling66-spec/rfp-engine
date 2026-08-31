"""Gates on the web (B37/D25): the whole pursuit walks intake ->
review ENTIRELY through HTTP (the v1 accept-test idiom), gate decisions
are mini-runs recording the OPERATOR (never a machine name), the redo
door works over the wire, and the waiver lane reaches the annotated
draft with its event. FakeCaller default app — dry_run, zero spend."""

import json

import pytest
from fastapi.testclient import TestClient

from engine.cli.slice import DEMO_PACK, DEMO_RAMBLE, DEMO_WORKBOOK
from engine.runlog import read_run
from engine.web.server import create_app
from tests.validation.fixtures.validations import (
    make_validation_script,
    run_validation_package,
)
from tests.web.conftest import (
    FIXED_AT,
    advance_past_gate0,
    raising_caller,
    sign_in,
    wait_job,
)

ROLE = {"actor_role": "pursuit_lead"}


@pytest.fixture(scope="module")
def walked(tmp_path_factory):
    """The full HTTP walk, shared: upload -> advance -> gate 1 (with an
    id-addressed kill) -> advance -> gate 2 (flag-all dispositions) ->
    advance -> drafting + validation -> review."""
    ws = tmp_path_factory.mktemp("web-gates") / "ws"
    app = create_app(ws, now=lambda: FIXED_AT)
    client = TestClient(app)
    client.__enter__()
    sign_in(client, "Ash Approver")
    client.post("/api/pursuits", json={"pursuit_id": "pur_walk"})
    for name, path in (("demo-twin.xlsx", DEMO_WORKBOOK),
                       ("ramble.md", DEMO_RAMBLE),
                       ("research-pack.md", DEMO_PACK)):
        client.put(f"/api/pursuits/pur_walk/inbox/{name}",
                   content=path.read_bytes())
    done = advance_past_gate0(client, "pur_walk")
    assert "awaiting_gate at gate_1" in done["message"]
    yield client, ws
    client.__exit__(None, None, None)


def test_gate1_model_and_id_addressed_decision(walked):
    client, ws = walked
    model = client.get("/api/pursuits/pur_walk/gate1").json()
    assert model["decidable"] is True
    ids = [c["candidate_id"] for c in model["candidates"]]
    assert ids and all(i.startswith("cand_") for i in ids)
    # P15-F2: the screen's flags come from procurement.red_flags — the old
    # top-level read rendered every Gate-1 screen flagless, hiding
    # wired_for_incumbent from the bid/no-bid decision it exists to inform.
    # The demo walk carries no flags, so this equality alone would be
    # vacuous — the planted-flag test below is the one that fires.
    brief = json.loads((ws / "pur_walk" / "brief.json").read_text())
    assert model["red_flags"] == brief["procurement"].get("red_flags", [])
    live = [c["candidate_id"] for c in model["candidates"]
            if c["status"] == "proposed"]
    r = client.post("/api/pursuits/pur_walk/gate1", json={
        "decision": "approved_with_edits",
        "edits": {"kill": [live[-1]]},
        "wait_ms": 120000, **ROLE,
        "effort": {"active_ms": 120000, "confirmed_minutes": 2}})
    assert r.status_code == 200 and r.json()["decision"] == \
        "approved_with_edits"
    brief = json.loads((ws / "pur_walk" / "brief.json").read_text())
    killed = next(c for c in brief["win_themes"]["candidates"]
                  if c["candidate_id"] == live[-1])
    assert killed["kill_reason"] == "killed at Gate 1 by Ash Approver"
    # the gate line records the OPERATOR + the wait; the mini-run closed
    runs = sorted((ws / "pur_walk" / "runs").glob("*/run.jsonl"))
    records = read_run(runs[-1])
    gate = next(r["gate"] for r in records if r["record_type"] == "gate")
    assert (gate["actor"], gate["wait_ms"]) == ("Ash Approver", 120000)
    assert records[-1]["run"]["status"] == "completed"
    # the one-click effort confirm rode along, both figures retained
    events = [json.loads(l) for l in (
        ws / "pur_walk" / "events" / "events.jsonl"
    ).read_text().splitlines()]
    conf = next(e for e in events if e["kind"] == "review_session")
    assert conf["effort"]["gate"] == "gate_1"
    assert conf["effort"]["active_ms"] == 120000
    assert conf["effort"]["confirmed_minutes"] == 2


def test_gate1_screen_shows_procurement_red_flags(walked):
    """The non-vacuous half of P15-F2 (dead-guard lesson: a declared rule
    needs a fixture that makes it fire): plant a wired_for_incumbent flag
    where intake actually writes flags and prove the screen renders it —
    under the old top-level read this list was ALWAYS empty."""
    client, ws = walked
    path = ws / "pur_walk" / "brief.json"
    original = path.read_text()
    brief = json.loads(original)
    planted = {"kind": "wired_for_incumbent",
               "detail": "spec matches the incumbent's product sheet",
               "detected_by": "model"}
    brief["procurement"].setdefault("red_flags", []).append(planted)
    path.write_text(json.dumps(brief, indent=2), encoding="utf-8")
    try:
        model = client.get("/api/pursuits/pur_walk/gate1").json()
        assert planted in model["red_flags"]
    finally:
        path.write_text(original, encoding="utf-8")


def test_gate2_model_shows_the_plan_and_decision_freezes(walked):
    client, ws = walked
    job = client.post("/api/pursuits/pur_walk/jobs",
                      json={"kind": "advance", "at": FIXED_AT}).json()
    assert "awaiting_gate at gate_2" in wait_job(client, job["id"])["message"]
    model = client.get("/api/pursuits/pur_walk/gate2").json()
    assert model["decidable"] is True
    assert model["themes_set"] is True and model["honesty"] is None
    assert model["sections"]  # the modal is never blank (UAT C2)
    open_gaps = [(s["section_id"], g["gap_id"])
                 for s in model["sections"] for g in s["gaps"]
                 if g["status"] == "open"]
    assert open_gaps
    for _, g in [g for g in open_gaps]:
        pass
    assert all(g["options"] == ["answered", "omit_approved", "reframed",
                                "draft_flagged"]
               for s in model["sections"] for g in s["gaps"]
               if g["status"] == "open")  # B24: four options, none preset
    dispose = [{"section_id": sid, "gap_id": gid,
                "action": "draft_flagged",
                "note": "Best effort; flag novel claims."}
               for sid, gid in open_gaps]
    r = client.post("/api/pursuits/pur_walk/gate2", json={
        "decision": "approved_with_edits", "edits": {"dispose": dispose},
        **ROLE})
    assert r.status_code == 200 and r.json()["frozen"] is True
    assert (ws / "pur_walk" / "plan.frozen.json").exists()


def test_walk_completes_to_review_through_http(walked):
    client, ws = walked
    job = client.post("/api/pursuits/pur_walk/jobs",
                      json={"kind": "advance", "at": FIXED_AT}).json()
    done = wait_job(client, job["id"], timeout=120)
    assert done["state"] == "done" and "advance complete" in done["message"]
    row = next(x for x in client.get("/api/pursuits").json()
               if x["pursuit_id"] == "pur_walk")
    assert row["stage"] == "review"
    assert (ws / "pur_walk" / "drafts" / "annotated-draft.json").exists()
    # every run in the walk is dry_run — the zero-spend default held
    for run_file in sorted((ws / "pur_walk" / "runs").glob("*/run.jsonl")):
        assert read_run(run_file)[0]["run"]["mode"] == "dry_run"


def test_gate_refusals_surface_as_409(walked):
    client, _ = walked
    # decide gate 1 if this test runs in isolation (module tests share
    # the walk); a CONFLICTING re-decision must then refuse (T7)
    if client.get("/api/pursuits/pur_walk/gate1").json()["decidable"]:
        client.post("/api/pursuits/pur_walk/gate1",
                    json={"decision": "approved", **ROLE})
    r = client.post("/api/pursuits/pur_walk/gate1",
                    json={"decision": "rejected", "notes": "changed mind",
                          **ROLE})
    assert r.status_code == 409, r.text
    # a settled gate 2 refuses a NEW decision (a same-args resubmission
    # would converge idempotently per B22(10) — so probe with a new at)
    r = client.post("/api/pursuits/pur_walk/gate2", json={
        "decision": "approved_with_edits",
        "edits": {"dispose": [{"section_id": "x", "gap_id": "y",
                               "action": "answered", "answer": "z"}]},
        "at": "2026-08-09T10:00:00", **ROLE})
    assert r.status_code == 409, r.text
    assert "already decided" in r.json()["detail"]


def test_gate2_rejection_is_the_redo_door_over_http(tmp_path):
    ws = tmp_path / "ws"
    app = create_app(ws, now=lambda: FIXED_AT)
    with TestClient(app) as client:
        sign_in(client, "Ray Redo")
        client.post("/api/pursuits", json={"pursuit_id": "pur_redo"})
        for name, path in (("demo-twin.xlsx", DEMO_WORKBOOK),
                           ("ramble.md", DEMO_RAMBLE),
                           ("research-pack.md", DEMO_PACK)):
            client.put(f"/api/pursuits/pur_redo/inbox/{name}",
                       content=path.read_bytes())
        advance_past_gate0(client, "pur_redo")
        client.post("/api/pursuits/pur_redo/gate1",
                    json={"decision": "approved", **ROLE})
        job = client.post("/api/pursuits/pur_redo/jobs",
                          json={"kind": "advance", "at": FIXED_AT}).json()
        wait_job(client, job["id"])
        # reject without notes refuses — feedback is the point of the redo
        no_notes = client.post("/api/pursuits/pur_redo/gate2",
                               json={"decision": "rejected", **ROLE})
        assert no_notes.status_code == 409
        r = client.post("/api/pursuits/pur_redo/gate2", json={
            "decision": "rejected",
            "notes": "Too thin on hypercare — replan with the SME pack.",
            **ROLE})
        assert r.status_code == 200
        plan = json.loads((ws / "pur_redo" / "plan.json").read_text())
        assert plan["status"] == "draft"  # the redo door, not a terminal
        # advancing again genuinely replans back to the gate
        job = client.post("/api/pursuits/pur_redo/jobs",
                          json={"kind": "advance", "at": FIXED_AT}).json()
        assert "awaiting_gate at gate_2" in wait_job(
            client, job["id"])["message"]


def test_collapse_stops_honest_when_gaps_exist(tmp_path):
    """The demo package carries gaps, so the one-screen collapse must NOT
    auto-approve gate 2 — B24: a human decision is never preselected."""
    ws = tmp_path / "ws"
    app = create_app(ws, now=lambda: FIXED_AT)
    with TestClient(app) as client:
        sign_in(client)
        client.post("/api/pursuits", json={"pursuit_id": "pur_clp"})
        for name, path in (("demo-twin.xlsx", DEMO_WORKBOOK),
                           ("ramble.md", DEMO_RAMBLE),
                           ("research-pack.md", DEMO_PACK)):
            client.put(f"/api/pursuits/pur_clp/inbox/{name}",
                       content=path.read_bytes())
        advance_past_gate0(client, "pur_clp")
        r = client.post("/api/pursuits/pur_clp/gate1",
                        json={"decision": "approved", "collapse": True,
                              **ROLE}).json()
        assert "job" in r  # the collapse enqueued planning
        done = wait_job(client, r["job"], timeout=120)
        assert done["state"] == "done"
        assert "never auto-disposes" in done["message"]
        plan = json.loads((ws / "pur_clp" / "plan.json").read_text())
        assert plan["status"] == "gate2_pending"  # stopped, not approved


def test_waiver_reaches_the_annotated_draft_with_its_event(tmp_path):
    pursuit, report, _ = run_validation_package(
        tmp_path, script=make_validation_script(plant_unsupported=True))
    app = create_app(tmp_path, make_caller=raising_caller,
                     now=lambda: FIXED_AT)
    with TestClient(app) as client:
        sign_in(client, "Wren Waiver")
        pid = pursuit.pursuit_id
        annotated = pursuit.read_artifact("drafts/annotated-draft.json")
        assert annotated["packaging"]["blocked"]
        blocked = next(c for s in annotated["sections"]
                       for c in s.get("claims", [])
                       if c["disposition"] == "block")
        r = client.post(f"/api/pursuits/{pid}/waivers", json={
            "claim_id": blocked["claim_id"],
            "reason": "Verified offline with the practice lead; evidence "
                      "attached to the pursuit file.", **ROLE})
        assert r.status_code == 200
        assert r.json() == {"status": "waived", "warnings": []}
        after = pursuit.read_artifact("drafts/annotated-draft.json")
        claim = next(c for s in after["sections"]
                     for c in s.get("claims", [])
                     if c["claim_id"] == blocked["claim_id"])
        assert claim["status"] == "waived"
        assert claim["waived_by"] == "Wren Waiver"
        events = [json.loads(l) for l in (
            pursuit.root / "events" / "events.jsonl"
        ).read_text().splitlines()]
        assert any(e["kind"] == "waive_block" for e in events)
        # boilerplate reason: recorded and SURFACED, never refused
        blocked2 = [c for s in after["sections"]
                    for c in s.get("claims", [])
                    if c["disposition"] == "block"]
        if blocked2:
            r2 = client.post(f"/api/pursuits/{pid}/waivers", json={
                "claim_id": blocked2[0]["claim_id"],
                "reason": "waived", **ROLE})
            assert r2.status_code == 200
            assert any("boilerplate" in w for w in r2.json()["warnings"])
