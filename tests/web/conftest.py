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
