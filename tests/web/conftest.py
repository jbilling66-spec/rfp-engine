"""tests/web shared plumbing. The offline-proof idiom (v1 keeper,
promoted): apps under test get a caller factory that RAISES — proving
deterministic routes never even ASK for a model, which a quietly unused
FakeCaller could not prove."""

import time

import pytest
from fastapi.testclient import TestClient

from engine.web.server import create_app

FIXED_AT = "2026-08-09T09:00:00"


def raising_caller(_log):
    raise AssertionError("this code path must never construct a caller")


@pytest.fixture()
def offline_app(tmp_path):
    app = create_app(tmp_path / "ws", make_caller=raising_caller,
                     now=lambda: FIXED_AT)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        yield client


@pytest.fixture(scope="module")
def live_server(tmp_path_factory):
    """W2a (B134): a real HTTP server for the browser smoke test — the
    same app object a TestClient seeded in-process (one pursuit, three
    inbox files, past gate 0 under FakeCaller), then uvicorn on a free
    loopback port in a daemon thread. Yields (base_url, workspace)."""
    import socket
    import threading

    import uvicorn

    from engine.cli.slice import DEMO_PACK, DEMO_RAMBLE, DEMO_WORKBOOK

    ws = tmp_path_factory.mktemp("web-smoke") / "ws"
    app = create_app(ws, now=lambda: FIXED_AT)  # default = FakeCaller
    with TestClient(app, base_url="http://127.0.0.1") as seed:
        sign_in(seed, "Sam Seeder")
        seed.post("/api/pursuits", json={"pursuit_id": "pur_smoke"})
        for name, path in (("demo-twin.xlsx", DEMO_WORKBOOK),
                           ("ramble.md", DEMO_RAMBLE),
                           ("research-pack.md", DEMO_PACK)):
            seed.put(f"/api/pursuits/pur_smoke/inbox/{name}",
                     content=path.read_bytes())
        done = advance_past_gate0(seed, "pur_smoke")
        assert "awaiting_gate at gate_1" in done["message"], done
        # P30b 2 (B141): one live share link, seeded here because the
        # browser's REAL clock would put a minted expiry 30+ days past the
        # server's frozen one (P3-12 refuses it); the smoke test revokes it
        r = seed.post("/api/pursuits/pur_smoke/share",
                      json={"label": "smoke guest",
                            "expires_at": "2026-08-16T09:00:00"})
        assert r.status_code == 200, r.text
        # P30a 5 (B139): a third, BARE pursuit — intake, nothing uploaded,
        # zero spend — so the board's filter and stage sort have something
        # to discriminate (stations 4 / 2 / 1)
        seed.post("/api/pursuits", json={"pursuit_id": "pur_blank"})
    # W2b 7 (B136, the owner's call): a second pursuit, REVIEWED, with one
    # revise round behind it, so the diff view, the Learned dialog and the
    # finish panel's hygiene line are proven in a browser — the offline
    # chain (intake → … → validation) lands `pur_gapcase` in the same
    # file-backed workspace; a second app over it, carrying the round
    # script, drives one comment → revise round and is discarded; the
    # served app reads the same files. Zero spend throughout.
    from engine.llm import FakeCaller, TracedCaller
    from tests.revision.fixtures.rounds import round_script
    from tests.validation.fixtures.validations import run_validation_package
    t0 = time.time()
    pursuit, report, _ = run_validation_package(ws)
    assert report.status == "complete", report
    assert pursuit.pursuit_id == "pur_gapcase"
    script = round_script()
    driver = create_app(ws, make_caller=lambda log: TracedCaller(FakeCaller(script), log),
                        now=lambda: FIXED_AT)
    with TestClient(driver, base_url="http://127.0.0.1") as drive:
        sign_in(drive, "Sam Seeder")
        model = drive.get("/api/pursuits/pur_gapcase/review").json()
        sid = next(s["section_id"] for s in model["sections"] if s["slots"])
        r = drive.post("/api/pursuits/pur_gapcase/comments", json={
            "kind": "comment", "section_id": sid,
            "text": "Lead with the transition story."})
        assert r.status_code == 200, r.text
        r = drive.post("/api/pursuits/pur_gapcase/revise", json={})
        assert r.status_code == 202, r.text
        job = wait_job(drive, r.json()["id"])
        assert job["state"] == "done", job["message"]
        assert "round 1: revised" in job["message"], job
    print(f"[smoke seed] the reviewed pursuit took {time.time() - t0:.1f}s")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(
        app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 30
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    assert server.started, "uvicorn did not start within 30s"
    try:
        yield f"http://127.0.0.1:{port}", ws
    finally:
        server.should_exit = True
        thread.join(10)


def sign_in(client, name="Jordan Reviewer", role="pursuit_lead") -> str:
    """Declares name AND role — the role is the session's, never a
    payload field (P27 wave 1, M-9)."""
    r = client.post("/api/session", json={"name": name, "role": role})
    assert r.status_code == 200, r.text
    return r.json()["operator"]


def wait_job(client, job_id, timeout=180.0) -> dict:
    # 180s, not 60: identical suite content has run 40s–11min under
    # external load (lessons.md), and a wait_job timeout mid-fixture
    # cascades 409s through every later test sharing the walk.
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["state"] not in ("queued", "running"):
            return job
        time.sleep(0.1)
    raise TimeoutError(f"job {job_id} still running after {timeout}s")


def advance_past_gate0(client, pursuit_id, at=FIXED_AT, timeout=120.0):
    """P15: the FIRST advance stops at gate_0 (intake review). Approve it
    plainly and re-advance — returns the second job's final record, which
    lands wherever the pre-P15 first advance used to land. Walks that
    exercise gate_0 itself post to /gate0 directly instead."""
    job = client.post(f"/api/pursuits/{pursuit_id}/jobs",
                      json={"kind": "advance"}).json()
    done = wait_job(client, job["id"], timeout=timeout)
    if "gate_0" not in done.get("message", ""):
        return done
    r = client.post(f"/api/pursuits/{pursuit_id}/gate0",
                    json={"decision": "approved"})
    assert r.status_code == 200, r.text
    job = client.post(f"/api/pursuits/{pursuit_id}/jobs",
                      json={"kind": "advance"}).json()
    return wait_job(client, job["id"], timeout=timeout)
