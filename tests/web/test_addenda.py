"""The addendum lane (B37/D18, G4): deterministic ADVISORY impact scan,
note_only routing into the review loop, and replan = the superseded
writer + the archived freeze + the redo door — every existing draft
voids by plan_sha256 mismatch, not by convention."""

import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from engine.cli.slice import DEMO_PACK, DEMO_RAMBLE, DEMO_WORKBOOK
from engine.web.server import create_app
from tests.validation.fixtures.validations import run_validation_package
from tests.web.conftest import advance_past_gate0, FIXED_AT, raising_caller, sign_in, wait_job

ROLE = {"actor_role": "pursuit_lead"}


@pytest.fixture(scope="module")
def amendable(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("web-addenda")
    pursuit, report, _ = run_validation_package(tmp)
    assert report.status == "complete"
    app = create_app(tmp, make_caller=raising_caller, now=lambda: FIXED_AT)
    with TestClient(app) as client:
        sign_in(client, "Ada Amender")
        yield client, pursuit


def test_impact_scan_ranks_the_named_section(amendable):
    client, pursuit = amendable
    pid = pursuit.pursuit_id
    plan = pursuit.read_artifact("plan.json")
    target = plan["sections"][0]
    terms = " ".join(target["title"].lower().split()[:4])
    body = (f"AMENDMENT 1: the buyer revises the expectations for "
            f"{terms} — responses must address the revised scope.")
    r = client.post(f"/api/pursuits/{pid}/addenda?filename=amend-1.md",
                    content=body.encode("utf-8"))
    assert r.status_code == 200, r.text
    meta = r.json()
    assert meta["addendum_id"] == "addm_01"
    assert meta["scanned"] is True
    assert meta["impacts"], "the named section must surface"
    assert meta["impacts"][0]["section_id"] == target["section_id"]
    assert meta["decision"] is None  # ADVISORY: the human decides
    listed = client.get(f"/api/pursuits/{pid}/addenda").json()
    assert [a["addendum_id"] for a in listed] == ["addm_01"]


def test_note_only_routes_impacts_into_the_review_loop(amendable):
    client, pursuit = amendable
    pid = pursuit.pursuit_id
    r = client.post(f"/api/pursuits/{pid}/addenda/addm_01/decide",
                    json={"decision": "note_only",
                          "note": "Fold into the next round.",
                          "at": FIXED_AT})
    assert r.status_code == 200
    pending = json.loads((pursuit.root / "events" / "pending.json"
                          ).read_text())["pending"]
    assert any("Addendum addm_01" in p.get("text", "") for p in pending)
    # a decided addendum refuses a second decision
    assert client.post(f"/api/pursuits/{pid}/addenda/addm_01/decide",
                       json={"decision": "replan", "note": "x",
                             "at": FIXED_AT}).status_code == 409


def test_replan_supersedes_archives_and_reopens_the_gate(tmp_path):
    """The void-by-mismatch chain (G4): superseded status (first writer),
    the freeze archived intact, the redo feedback consumed, and the
    old draft's plan_sha256 no longer matches any live freeze."""
    ws = tmp_path / "ws"
    from engine.llm import FakeCaller, TracedCaller
    from engine.web.fake_script import revision_script
    app = create_app(ws, make_caller=lambda log: TracedCaller(
        FakeCaller(revision_script()), log), now=lambda: FIXED_AT)
    with TestClient(app) as client:
        sign_in(client, "Ada Amender")
        client.post("/api/pursuits", json={"pursuit_id": "pur_amend"})
        for name, path in (("demo-twin.xlsx", DEMO_WORKBOOK),
                           ("ramble.md", DEMO_RAMBLE),
                           ("research-pack.md", DEMO_PACK)):
            client.put(f"/api/pursuits/pur_amend/inbox/{name}",
                       content=path.read_bytes())
        advance_past_gate0(client, "pur_amend", timeout=180)
        client.post("/api/pursuits/pur_amend/gate1",
                    json={"decision": "approved", **ROLE})
        wait_job(client, client.post(
            "/api/pursuits/pur_amend/jobs",
            json={"kind": "advance", "at": FIXED_AT}).json()["id"],
            timeout=180)
        g2 = client.get("/api/pursuits/pur_amend/gate2").json()
        dispose = [{"section_id": s["section_id"], "gap_id": g["gap_id"],
                    "action": "draft_flagged", "note": "Best effort."}
                   for s in g2["sections"] for g in s["gaps"]
                   if g["status"] == "open"]
        client.post("/api/pursuits/pur_amend/gate2", json={
            "decision": "approved_with_edits",
            "edits": {"dispose": dispose}, **ROLE})
        wait_job(client, client.post(
            "/api/pursuits/pur_amend/jobs",
            json={"kind": "advance", "at": FIXED_AT}).json()["id"],
            timeout=180)
        old_frozen_sha = hashlib.sha256(
            (ws / "pur_amend" / "plan.frozen.json").read_bytes()
        ).hexdigest()
        old_envelope = json.loads(
            (ws / "pur_amend" / "drafts" / "draft.json").read_text())
        assert old_envelope["plan_sha256"] == old_frozen_sha
        client.post("/api/pursuits/pur_amend/addenda?filename=a2.md",
                    content=b"AMENDMENT: scope change to the timeline.")
        r = client.post("/api/pursuits/pur_amend/addenda/addm_01/decide",
                        json={"decision": "replan",
                              "note": "Timeline scope changed — replan.",
                              "at": FIXED_AT})
        assert r.status_code == 200
        plan = json.loads((ws / "pur_amend" / "plan.json").read_text())
        assert plan["status"] == "superseded"  # the first writer
        assert not (ws / "pur_amend" / "plan.frozen.json").exists()
        archived = (ws / "pur_amend" / "addenda" / "addm_01"
                    / "plan.frozen.superseded.json")
        assert hashlib.sha256(archived.read_bytes()).hexdigest() \
            == old_frozen_sha  # moved INTACT, never rewritten
        # the NORMAL lane re-plans, consuming the addendum note as the
        # redo feedback, back to a decidable gate
        done = wait_job(client, client.post(
            "/api/pursuits/pur_amend/jobs",
            json={"kind": "advance", "at": FIXED_AT}).json()["id"],
            timeout=180)
        assert "awaiting_gate at gate_2" in done["message"]
        new_plan = json.loads(
            (ws / "pur_amend" / "plan.json").read_text())
        assert new_plan["status"] == "gate2_pending"
        # the old draft is void by MISMATCH: no live freeze carries its
        # plan_sha256 anymore
        assert not (ws / "pur_amend" / "plan.frozen.json").exists()
