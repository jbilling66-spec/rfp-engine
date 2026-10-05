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



@pytest.fixture(scope="module")
def amendable(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("web-addenda")
    pursuit, report, _ = run_validation_package(tmp)
    assert report.status == "complete"
    app = create_app(tmp, make_caller=raising_caller, now=lambda: FIXED_AT)
    with TestClient(app, base_url="http://127.0.0.1") as client:
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
                          "note": "Fold into the next round."})
    assert r.status_code == 200
    pending = json.loads((pursuit.root / "events" / "pending.json"
                          ).read_text())["pending"]
    assert any("Addendum addm_01" in p.get("text", "") for p in pending)
    # a decided addendum refuses a second decision
    assert client.post(f"/api/pursuits/{pid}/addenda/addm_01/decide",
                       json={"decision": "replan", "note": "x"}).status_code == 409


def test_replan_supersedes_archives_and_reopens_the_gate(tmp_path):
    """The void-by-mismatch chain (G4): superseded status (first writer),
    the freeze archived intact, the redo feedback consumed, and the
    old draft's plan_sha256 no longer matches any live freeze."""
    ws = tmp_path / "ws"
    from engine.llm import FakeCaller, TracedCaller
    from engine.web.fake_script import revision_script
    app = create_app(ws, make_caller=lambda log: TracedCaller(
        FakeCaller(revision_script()), log), now=lambda: FIXED_AT)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        sign_in(client, "Ada Amender")
        client.post("/api/pursuits", json={"pursuit_id": "pur_amend"})
        for name, path in (("demo-twin.xlsx", DEMO_WORKBOOK),
                           ("ramble.md", DEMO_RAMBLE),
                           ("research-pack.md", DEMO_PACK)):
            client.put(f"/api/pursuits/pur_amend/inbox/{name}",
                       content=path.read_bytes())
        advance_past_gate0(client, "pur_amend", timeout=180)
        client.post("/api/pursuits/pur_amend/gate1",
                    json={"decision": "approved"})
        wait_job(client, client.post(
            "/api/pursuits/pur_amend/jobs",
            json={"kind": "advance"}).json()["id"],
            timeout=180)
        g2 = client.get("/api/pursuits/pur_amend/gate2").json()
        dispose = [{"section_id": s["section_id"], "gap_id": g["gap_id"],
                    "action": "draft_flagged", "note": "Best effort."}
                   for s in g2["sections"] for g in s["gaps"]
                   if g["status"] == "open"]
        client.post("/api/pursuits/pur_amend/gate2", json={
            "decision": "approved_with_edits",
            "edits": {"dispose": dispose}})
        wait_job(client, client.post(
            "/api/pursuits/pur_amend/jobs",
            json={"kind": "advance"}).json()["id"],
            timeout=180)
        old_frozen_sha = hashlib.sha256(
            (ws / "pur_amend" / "plan.frozen.json").read_bytes()
        ).hexdigest()
        old_envelope = json.loads(
            (ws / "pur_amend" / "drafts" / "draft.json").read_text())
        assert old_envelope["plan_sha256"] == old_frozen_sha
        old_draft_sha = hashlib.sha256(
            (ws / "pur_amend" / "drafts" / "draft.json").read_bytes()
        ).hexdigest()
        client.post("/api/pursuits/pur_amend/addenda?filename=a2.md",
                    content=b"AMENDMENT: scope change to the timeline.")
        r = client.post("/api/pursuits/pur_amend/addenda/addm_01/decide",
                        json={"decision": "replan",
                              "note": "Timeline scope changed — replan."})
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
            json={"kind": "advance"}).json()["id"],
            timeout=180)
        assert "awaiting_gate at gate_2" in done["message"]
        new_plan = json.loads(
            (ws / "pur_amend" / "plan.json").read_text())
        assert new_plan["status"] == "gate2_pending"
        # the old draft is void by MISMATCH: no live freeze carries its
        # plan_sha256 anymore
        assert not (ws / "pur_amend" / "plan.frozen.json").exists()

        # --- P25 item 8 (P0-16): the pre-amendment draft pair is archived
        # intact and attested, the drafting/validation checkpoints are
        # cleared, a re-approved replan refuses the stale export, and the
        # next advance drafts anew against the current plan.
        from engine.pipeline.driver import validation_is_current
        from engine.workspace import PursuitDir
        pursuit = PursuitDir(ws, "pur_amend")
        root = pursuit.root
        meta = json.loads((root / "addenda" / "addm_01" / "meta.json")
                          .read_text(encoding="utf-8"))
        assert meta["archived_draft_sha256"] == old_draft_sha
        assert not (root / "drafts" / "draft.json").exists()
        archived_draft = root / "addenda" / "addm_01" / "draft.superseded.json"
        assert hashlib.sha256(archived_draft.read_bytes()).hexdigest() \
            == old_draft_sha
        assert not {"drafting", "validation"} & pursuit.completed_stages()
        g2 = client.get("/api/pursuits/pur_amend/gate2").json()
        dispose = [{"section_id": s["section_id"], "gap_id": g["gap_id"],
                    "action": "draft_flagged", "note": "Best effort."}
                   for s in g2["sections"] for g in s["gaps"]
                   if g["status"] == "open"]
        r = client.post("/api/pursuits/pur_amend/gate2", json={
            "decision": "approved_with_edits",
            "edits": {"dispose": dispose}})
        assert r.status_code == 200, r.text
        new_frozen_sha = pursuit.file_sha256("plan.frozen.json")
        assert new_frozen_sha
        # Under FakeCaller the replan can reproduce the plan BYTE-FOR-BYTE
        # (same script, same clock) — the old draft's plan_sha256 would
        # then match the new freeze, which is exactly why the replan
        # ARCHIVES the draft pair instead of trusting the hash alone.
        # the stale export is REFUSED (no current draft for this plan)
        r = client.post("/api/pursuits/pur_amend/export",
                        json={"lane": "submission"})
        assert r.status_code == 409, r.text
        assert not (root / "exports" / "submission").exists() or not any(
            (root / "exports" / "submission").iterdir())
        # the next advance drafts and validates against the CURRENT plan
        done = wait_job(client, client.post(
            "/api/pursuits/pur_amend/jobs",
            json={"kind": "advance"}).json()["id"],
            timeout=240)
        assert done["state"] == "done", done
        new_envelope = json.loads((root / "drafts" / "draft.json").read_text())
        assert new_envelope["plan_sha256"] == new_frozen_sha
        assert validation_is_current(pursuit)
        # whatever the export door says now, it is no longer staleness
        r = client.post("/api/pursuits/pur_amend/export",
                        json={"lane": "submission"})
        assert "different frozen plan" not in r.text
        assert "does not match" not in r.text


def test_the_addenda_door_refuses_the_lanes_own_record_names(amendable):
    """P3-21 (P29b b3): an addendum named `meta.json` overwrote the
    lane's own record — the buyer amendment's bytes gone while the record
    said `scanned: true`; the replan archive names collide the same way.
    Refused by name with the inbox door's posture; a plain filename is
    still required rather than collapsed."""
    client, pursuit = amendable
    pid = pursuit.pursuit_id
    before = client.get(f"/api/pursuits/{pid}/addenda").json()
    for name in ("meta.json", "draft.superseded.json",
                 "plan.frozen.superseded.json"):
        r = client.post(f"/api/pursuits/{pid}/addenda?filename={name}",
                        content=b"# amendment\n")
        assert r.status_code == 422, (name, r.text)
        assert "reserved filename" in r.json()["detail"]
    r = client.post(f"/api/pursuits/{pid}/addenda?filename=..%2Fmeta.json",
                    content=b"# amendment\n")
    assert r.status_code == 422 and "plain filenames" in r.json()["detail"]
    assert client.get(f"/api/pursuits/{pid}/addenda").json() == before
    for meta_path in (pursuit.root / "addenda").glob("addm_*/meta.json"):
        json.loads(meta_path.read_text(encoding="utf-8"))["addendum_id"]


def test_addendum_ids_mint_from_the_lane_max_not_a_count(tmp_path):
    """Same touch (the P1-20/P1-22 rule): `len+1` collided after a
    deleted folder; the id is max+1."""
    from engine.web.addenda import AddendumLane
    from engine.workspace import PursuitDir
    pursuit = PursuitDir(tmp_path, "pur_am")
    (pursuit.root / "plan.json").write_text(json.dumps({
        "pursuit_id": "pur_am", "sections": []}), encoding="utf-8")
    lane = AddendumLane(pursuit)
    for aid in ("addm_01", "addm_03"):
        (lane.root / aid).mkdir(parents=True)
    meta = lane.store(filename="a.md", body=b"# a\n", at=FIXED_AT,
                      actor="t", slots_by_id=None)
    assert meta["addendum_id"] == "addm_04"


def test_a_meta_that_fails_its_schema_refuses_the_lane_by_name(tmp_path):
    """P32b (B145 §3d/§3i): the meta holds a human decision and the
    attested archive digests — one that breaks its contract refuses the
    list and the decide doors (409 naming the file), never rewritten."""
    pursuit, report, _ = run_validation_package(tmp_path)
    assert report.status == "complete"
    folder = pursuit.root / "addenda" / "addm_07"
    folder.mkdir(parents=True)
    (folder / "meta.json").write_text(json.dumps({"addendum_id": "addm_07"}),
                                      encoding="utf-8")
    app = create_app(tmp_path, make_caller=raising_caller, now=lambda: FIXED_AT)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        sign_in(client, "Ada Amender")
        pid = pursuit.pursuit_id
        r = client.get(f"/api/pursuits/{pid}/addenda")
        assert r.status_code == 409, r.text
        assert "addenda/addm_07/meta.json fails its schema" in r.json()["detail"]
        r = client.post(f"/api/pursuits/{pid}/addenda/addm_07/decide",
                        json={"decision": "note_only", "note": ""})
        assert r.status_code == 409 and "fails its schema" in r.json()["detail"]
    assert json.loads((folder / "meta.json").read_text()) == {"addendum_id": "addm_07"}
