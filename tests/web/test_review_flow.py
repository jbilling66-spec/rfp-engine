"""Revision over the wire (B37/D6/D7, F9): the acceptance clause's
route-driven twin — comment -> revise job -> revision N+1 with replies
visible, the F9 render model (mark + one-line leads, forensic detail
nested, artifact untouched), the server-computed diff, and revise as
the FIRST cancellable kind."""

import json

import pytest
from fastapi.testclient import TestClient

from engine.web.fake_script import revision_script
from engine.web.jobs import CANCELLABLE_KINDS
from engine.web.server import create_app
from tests.revision.fixtures.rounds import round_script
from tests.validation.fixtures.validations import run_validation_package
from tests.web.conftest import FIXED_AT, sign_in, wait_job

ROLE = {"actor_role": "pursuit_lead"}


@pytest.fixture(scope="module")
def reviewing(tmp_path_factory):
    """A validated pursuit served with a caller whose script carries the
    revision arm (the P8 chain + the product-side derive)."""
    from engine.llm import FakeCaller, TracedCaller
    tmp = tmp_path_factory.mktemp("web-review")
    pursuit, report, _ = run_validation_package(tmp)
    assert report.status == "complete"
    script = round_script()

    def make_caller(log):
        return TracedCaller(FakeCaller(script), log)

    app = create_app(tmp, make_caller=make_caller, now=lambda: FIXED_AT)
    client = TestClient(app)
    client.__enter__()
    sign_in(client, "Remy Reviewer")
    yield client, pursuit
    client.__exit__(None, None, None)


def test_review_model_leads_with_marks_not_forensics(reviewing):
    client, pursuit = reviewing
    m = client.get(f"/api/pursuits/{pursuit.pursuit_id}/review").json()
    assert m["revision_n"] == 0
    assert m["sections"]
    drafted = [s for s in m["sections"] if s["slots"]]
    assert drafted, "the render model carries the prose under review"
    marked = [k for s in m["sections"] for k in s.get("marks", [])]
    assert marked, "the P8 chain plants findings — marks must exist"
    for mark in marked:
        assert mark["mark"] in ("block", "review", "advisory", "waived",
                                "ok")
        assert mark["line"] and len(mark["line"]) <= 120  # one line, F9
        assert "detail" in mark  # the forensic row, on demand
    # rendering only: the artifact keeps its full forensic shape
    annotated = pursuit.read_artifact("drafts/annotated-draft.json")
    assert "marks" not in json.dumps(annotated)


def test_comment_then_revise_over_http(reviewing):
    client, pursuit = reviewing
    pid = pursuit.pursuit_id
    m = client.get(f"/api/pursuits/{pid}/review").json()
    sid = next(s["section_id"] for s in m["sections"] if s["slots"])
    entry = client.post(f"/api/pursuits/{pid}/comments", json={
        "kind": "comment", "section_id": sid,
        "text": "Lead with the transition story.", **ROLE}).json()
    # the pending overlay shows it before any round runs
    m = client.get(f"/api/pursuits/{pid}/review").json()
    row = next(s for s in m["sections"] if s["section_id"] == sid)
    assert [p["cid"] for p in row["pending"]] == [entry["cid"]]
    r = client.post(f"/api/pursuits/{pid}/revise", json={"at": FIXED_AT})
    assert r.status_code == 202
    job = wait_job(client, r.json()["id"])
    assert job["state"] == "done", job["message"]
    assert "round 1: revised" in job["message"]
    m = client.get(f"/api/pursuits/{pid}/review").json()
    assert m["revision_n"] == 1
    # the finalized comment carries the agent's reply
    events = [json.loads(l) for l in (
        pursuit.root / "events" / "events.jsonl"
    ).read_text().splitlines()]
    comment = next(e for e in events if e["kind"] == "comment")
    assert comment["agent_reply"] == f"Addressed {entry['cid']}."
    # revision history + the server-computed diff
    rounds = client.get(f"/api/pursuits/{pid}/revisions").json()
    assert [r["round_n"] for r in rounds] == [1]
    diff = client.get(f"/api/pursuits/{pid}/revisions/1").json()
    assert diff["record"]["round_n"] == 1
    assert diff["diff"], "a revised round must show changed text"
    assert all(d["before"] != d["after"] for d in diff["diff"])


def test_empty_revise_refuses_over_http(reviewing):
    client, pursuit = reviewing
    r = client.post(f"/api/pursuits/{pursuit.pursuit_id}/revise",
                    json={"at": FIXED_AT})
    job = wait_job(client, r.json()["id"])
    assert job["state"] == "refused"
    assert "revision_n never bumps" in job["message"]


def test_revise_is_the_first_cancellable_kind():
    assert CANCELLABLE_KINDS == frozenset({"revise"})
    assert callable(revision_script()["revision_agent"])


def test_serve_default_covers_the_revision_lane():
    """The serve default must script EVERY dry_run agent — an unscripted
    revision_agent echoes non-JSON and the clickable review loop refuses
    (caught seeding the J7 look-and-feel demo)."""
    from engine.llm import FakeCaller
    from engine.web.server import _default_make_caller

    class _Log:
        def emit(self, *a, **k):
            pass

    caller = _default_make_caller(_Log())
    fake = caller.caller if hasattr(caller, "caller") else caller.fake
    assert isinstance(fake, FakeCaller)
    assert "revision_agent" in fake.script
