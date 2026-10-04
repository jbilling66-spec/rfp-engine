"""P30b 1 (B141): two additive reads the behaviours slice keys on.

`job` — the detail and the review payloads name the pursuit's live job
(id, kind, state, message, cancellable) while the runner holds one, and
carry no key at all otherwise, so the shell can disable the pursuit's
buttons on the SERVER's word (B134 §1d's `busy`) instead of inferring
it from the strip it happens to be polling. `outcome` — the last
recorded outcome event, read back from the events lane, so the Outcome
panel can show what was recorded. Three-state throughout."""

import threading

import pytest
from fastapi.testclient import TestClient

from engine.web.server import create_app
from tests.validation.fixtures.validations import run_validation_package
from tests.web.conftest import FIXED_AT, raising_caller, sign_in, wait_job


@pytest.fixture(scope="module")
def reviewed(tmp_path_factory):
    """A reviewed pursuit (the offline validation chain) under an app
    whose caller RAISES — neither read below may ask for a model."""
    ws = tmp_path_factory.mktemp("web-busy") / "ws"
    pursuit, report, _ = run_validation_package(ws)
    assert report.status == "complete", report
    app = create_app(ws, make_caller=raising_caller, now=lambda: FIXED_AT)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        sign_in(client)
        yield client, pursuit.pursuit_id


def test_a_live_job_is_named_on_the_detail_and_the_review(reviewed):
    client, pid = reviewed
    runner = client.app.state.runner
    started, release = threading.Event(), threading.Event()

    def slow(job):
        started.set()
        release.wait(timeout=30)
        return "done", "slow done"

    job = runner.submit(kind="advance", pursuit_id=pid, by="test",
                        at=FIXED_AT, target=slow)
    try:
        assert started.wait(timeout=10), "the worker never picked the job up"
        d = client.get(f"/api/pursuits/{pid}").json()
        assert set(d["job"]) == {"id", "kind", "state", "message", "cancellable"}
        assert d["job"]["id"] == job["id"]
        assert (d["job"]["kind"], d["job"]["state"]) == ("advance", "running")
        assert d["job"]["cancellable"] is False  # a running advance cannot stop
        m = client.get(f"/api/pursuits/{pid}/review").json()
        assert m["job"]["id"] == job["id"] and m["job"]["state"] == "running"
    finally:
        release.set()
    assert wait_job(client, job["id"])["state"] == "done"
    # three-state: no live job, no key — on both payloads
    assert "job" not in client.get(f"/api/pursuits/{pid}").json()
    assert "job" not in client.get(f"/api/pursuits/{pid}/review").json()


def test_the_recorded_outcome_is_read_back_on_the_detail(reviewed):
    client, pid = reviewed
    assert "outcome" not in client.get(f"/api/pursuits/{pid}").json()
    r = client.post(f"/api/pursuits/{pid}/outcome",
                    json={"result": "shortlisted"})  # the server stamps `at`
    assert r.status_code == 200, r.text
    d = client.get(f"/api/pursuits/{pid}").json()
    assert d["outcome"] == {"result": "shortlisted", "at": FIXED_AT,
                            "by": "Jordan Reviewer"}
    # the LAST record is the one shown
    r = client.post(f"/api/pursuits/{pid}/outcome",
                    json={"result": "won"})
    assert r.status_code == 200, r.text
    assert client.get(f"/api/pursuits/{pid}").json()["outcome"]["result"] == "won"


def test_a_bare_pursuit_carries_neither_key(offline_app):
    sign_in(offline_app, "Bare Reader")
    r = offline_app.post("/api/pursuits", json={"pursuit_id": "pur_bare"})
    assert r.status_code < 300, r.text
    d = offline_app.get("/api/pursuits/pur_bare").json()
    assert "job" not in d and "outcome" not in d
