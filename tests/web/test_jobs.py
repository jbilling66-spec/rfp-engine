"""The job runner (B37/D2): the one-job-per-pursuit 409 (the test v1
never wrote), the append-only journal + orphan rehydration, the typed
error lanes, and the advance job driving the REAL pipeline through HTTP
to an honest awaiting_gate stop."""

import json

import pytest
from fastapi.testclient import TestClient

from engine.cli.slice import DEMO_PACK, DEMO_RAMBLE, DEMO_WORKBOOK
from engine.contracts import ContractError
from engine.web.jobs import JobRunner
from engine.web.server import create_app
from tests.web.conftest import FIXED_AT, sign_in, wait_job


@pytest.fixture(scope="module")
def demo_client(tmp_path_factory):
    """A real pursuit advanced through HTTP under FakeCaller — module
    scoped because the advance runs three real stages."""
    ws = tmp_path_factory.mktemp("web-jobs") / "ws"
    app = create_app(ws, now=lambda: FIXED_AT)  # default = FakeCaller
    with TestClient(app, base_url="http://127.0.0.1") as client:
        sign_in(client)
        client.post("/api/pursuits", json={"pursuit_id": "pur_webdemo"})
        for name, path in (("demo-twin.xlsx", DEMO_WORKBOOK),
                           ("ramble.md", DEMO_RAMBLE),
                           ("research-pack.md", DEMO_PACK)):
            client.put(f"/api/pursuits/pur_webdemo/inbox/{name}",
                       content=path.read_bytes())
        yield client, ws


def test_advance_job_stops_at_each_gate_in_order(demo_client):
    """P15: the FIRST stop is gate_0 — the intake review, before any
    research spend — and the board says so; a plain approval then walks
    the next advance to gate_1 exactly as before."""
    client, ws = demo_client
    r = client.post("/api/pursuits/pur_webdemo/jobs",
                    json={"kind": "advance", "at": FIXED_AT})
    assert r.status_code == 202
    job = wait_job(client, r.json()["id"])
    assert job["state"] == "done"
    assert "awaiting_gate at gate_0" in job["message"]
    board = client.get("/api/pursuits").json()
    row = next(x for x in board if x["pursuit_id"] == "pur_webdemo")
    assert row["stage"] == "gate_0"
    assert "gate 0" in row["next"]
    runs = client.get("/api/pursuits/pur_webdemo/runs").json()
    assert len(runs) == 1  # the stop lives INSIDE the intake run
    assert runs[-1]["status"] == "awaiting_gate"

    model = client.get("/api/pursuits/pur_webdemo/gate0").json()
    assert model["decidable"] is True
    assert model["assumptions"]  # the register is on the screen
    ok = client.post("/api/pursuits/pur_webdemo/gate0",
                     json={"decision": "approved", "at": FIXED_AT})
    assert ok.status_code == 200 and ok.json()["decision"] == "approved"

    r = client.post("/api/pursuits/pur_webdemo/jobs",
                    json={"kind": "advance", "at": FIXED_AT})
    job = wait_job(client, r.json()["id"])
    assert "awaiting_gate at gate_1" in job["message"]
    row = next(x for x in client.get("/api/pursuits").json()
               if x["pursuit_id"] == "pur_webdemo")
    assert row["stage"] == "gate_1"
    assert "Gate 1" in row["next"]
    detail = client.get("/api/pursuits/pur_webdemo").json()
    assert detail["brief_status"] == "gate1_pending"
    assert detail["totals"]["cost_source"] == "run_totals"
    runs = client.get("/api/pursuits/pur_webdemo/runs").json()
    assert runs[-1]["status"] == "awaiting_gate"
    assert all(r["mode"] == "dry_run" for r in runs)  # zero spend default


def test_one_job_per_pursuit_409(demo_client):
    """THE lock test v1 never wrote. A slow job holds the lane; a second
    submission is a 409 naming the running job, never a silent queue."""
    client, _ = demo_client
    import threading
    release = threading.Event()
    runner = client.app.state.runner

    def slow(job):
        release.wait(timeout=30)
        return "done", "slow done"

    first = runner.submit(kind="advance", pursuit_id="pur_webdemo",
                          by="test", at=FIXED_AT, target=slow)
    try:
        r = client.post("/api/pursuits/pur_webdemo/jobs",
                        json={"kind": "advance", "at": FIXED_AT})
        assert r.status_code == 409
        assert "one job per pursuit" in r.json()["detail"]
        assert first["id"] in r.json()["detail"]
    finally:
        release.set()
    assert wait_job(client, first["id"])["state"] == "done"


def test_typed_error_lanes(demo_client):
    client, _ = demo_client
    runner = client.app.state.runner

    def refuses(job):
        raise ContractError("a rule said no")

    def crashes(job):
        raise ValueError("boom")

    refused = runner.submit(kind="advance", pursuit_id="pur_webdemo",
                            by="test", at=FIXED_AT, target=refuses)
    refused = wait_job(client, refused["id"])
    assert (refused["state"], refused["message"]) == (
        "refused", "a rule said no")  # the system working, not a bug
    crashed = runner.submit(kind="advance", pursuit_id="pur_webdemo",
                            by="test", at=FIXED_AT, target=crashes)
    crashed = wait_job(client, crashed["id"])
    assert crashed["state"] == "error"
    assert crashed["message"] == "ValueError: boom"


def test_cancel_lanes(demo_client):
    client, _ = demo_client
    assert client.post("/api/jobs/job-9999/cancel").status_code == 404
    done = client.get("/api/jobs").json()[0]
    r = client.post(f"/api/jobs/{done['id']}/cancel")
    assert r.status_code == 409
    assert f"already {done['state']}" in r.json()["detail"]


def test_journal_rehydration_flips_dead_running_to_orphaned(tmp_path):
    journal = tmp_path / "jobs.jsonl"
    lines = [
        {"id": "job-0001", "kind": "advance", "pursuit": "pur_a",
         "by": "x", "at": FIXED_AT, "state": "running",
         "message": "drafting section 3"},
        {"id": "job-0002", "kind": "advance", "pursuit": "pur_b",
         "by": "x", "at": FIXED_AT, "state": "done", "message": "ok"},
    ]
    journal.write_text("".join(json.dumps(l) + "\n" for l in lines),
                       encoding="utf-8")
    runner = JobRunner(tmp_path)
    j1 = runner.job("job-0001")
    assert j1["state"] == "orphaned"
    assert "server restarted mid-run" in j1["message"]
    assert "drafting section 3" in j1["message"]  # the old message kept
    assert runner.job("job-0002")["state"] == "done"
    # the flip was journaled (append-only history, last line wins)
    raw = [json.loads(l) for l in
           journal.read_text(encoding="utf-8").splitlines()]
    assert raw[-1]["id"] == "job-0001" and raw[-1]["state"] == "orphaned"
    # and the id counter resumed PAST the dead jobs
    nxt = runner.submit(kind="advance", pursuit_id="pur_c", by="x",
                        at=FIXED_AT, target=lambda job: ("done", "ok"))
    assert nxt["id"] == "job-0003"
