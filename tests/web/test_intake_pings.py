"""Intake gaps join the ping lane (P15/C6): pingable and answerable
PRE-PLAN over the brief's intake.gaps — the join that could never be
made while intake questions existed only as run-log lines. The lane
refuses once the brief freezes (Gate 1): a settled record takes no
quiet edits. FakeCaller default app — dry_run, zero spend."""

import json

import pytest
from fastapi.testclient import TestClient

from engine.cli.slice import DEMO_PACK, DEMO_RAMBLE, DEMO_WORKBOOK
from engine.web.fake_script import revision_script
from engine.llm import FakeCaller, TracedCaller
from engine.runlog import read_run
from engine.web.server import create_app
from tests.web.conftest import FIXED_AT, sign_in, wait_job



def _starving_caller(log):
    """The CI wire with what_is_bought withheld — the walk lands at
    gate_0 carrying a real completeness gap to ping."""
    script = dict(revision_script())
    base = script["intake_analyst"]

    def starve(prompt: str) -> str:
        wire = json.loads(base(prompt) if callable(base) else base)
        wire["procurement"].pop("what_is_bought", None)
        return json.dumps(wire)

    script["intake_analyst"] = starve
    return TracedCaller(FakeCaller(script), log)


@pytest.fixture(scope="module")
def gapped_walk(tmp_path_factory):
    ws = tmp_path_factory.mktemp("web-intake-pings") / "ws"
    app = create_app(ws, make_caller=_starving_caller,
                     now=lambda: FIXED_AT)
    client = TestClient(app, base_url="http://127.0.0.1")
    client.__enter__()
    sign_in(client, "Pia Pinger")
    client.post("/api/pursuits", json={"pursuit_id": "pur_ig"})
    for name, path in (("demo-twin.xlsx", DEMO_WORKBOOK),
                       ("ramble.md", DEMO_RAMBLE),
                       ("research-pack.md", DEMO_PACK)):
        client.put(f"/api/pursuits/pur_ig/inbox/{name}",
                   content=path.read_bytes())
    job = client.post("/api/pursuits/pur_ig/jobs",
                      json={"kind": "advance"}).json()
    done = wait_job(client, job["id"])
    assert "gate_0" in done["message"]
    yield client, ws
    client.__exit__(None, None, None)


def test_intake_gap_pings_and_answers_pre_plan(gapped_walk):
    client, ws = gapped_walk
    brief = json.loads((ws / "pur_ig" / "brief.json").read_text())
    gap = next(g for g in brief["intake"]["gaps"]
               if g["target"] == "procurement.what_is_bought")

    r = client.post(f"/api/pursuits/pur_ig/gaps/{gap['gap_id']}/ping",
                    json={"route_to": "sme"})
    assert r.status_code == 200, r.text
    ping = r.json()
    assert ping["section_id"] == "intake"

    # the brief's vocabulary has no "pinged" — the gap stays open so
    # gate_0 can still take its answer at decision time
    brief = json.loads((ws / "pur_ig" / "brief.json").read_text())
    gap_now = next(g for g in brief["intake"]["gaps"]
                   if g["gap_id"] == gap["gap_id"])
    assert gap_now["status"] == "open"

    # the inbox carries it, and the injected clock escalates it (>24h)
    client.app.state.clock = lambda: "2026-08-11T09:00:01"  # P2-47
    inbox = client.get("/api/pursuits/pur_ig/pings").json()
    client.app.state.clock = lambda: FIXED_AT
    row = next(x for x in inbox if x["gap_id"] == gap["gap_id"])
    assert row["escalated"] is True

    r = client.post(f"/api/pursuits/pur_ig/pings/{ping['ping_id']}/answer",
                    json={"answer": "ERP managed services transition"})
    assert r.status_code == 200, r.text
    brief = json.loads((ws / "pur_ig" / "brief.json").read_text())
    gap_now = next(g for g in brief["intake"]["gaps"]
                   if g["gap_id"] == gap["gap_id"])
    assert gap_now["status"] == "answered"
    assert gap_now["answer"] == "ERP managed services transition"
    assert gap_now["answered_by"] == "Pia Pinger"

    # the run-log lines carry the gap's OWN reason, not the plan lane's
    # hardcoded kb_empty
    runs = sorted((ws / "pur_ig" / "runs").glob("*/run.jsonl"))
    lines = [r["gap"] for f in runs for r in read_run(f)
             if r["record_type"] == "gap"
             and r["gap"].get("gap_id") == gap["gap_id"]]
    assert any(line.get("resolution") == "answered" for line in lines)
    assert all(line["reason"] == gap["reason"] for line in lines)


def test_unknown_intake_gap_409s(gapped_walk):
    client, _ = gapped_walk
    r = client.post("/api/pursuits/pur_ig/gaps/gap_nope_01/ping",
                    json={"route_to": "sme"})
    assert r.status_code == 409
    assert "no gap" in r.json()["detail"]


def test_frozen_brief_refuses_intake_pings(gapped_walk):
    """Gate 1 settles the intake record: pings against a frozen brief
    refuse loudly rather than quietly editing a settled artifact."""
    client, ws = gapped_walk
    brief = json.loads((ws / "pur_ig" / "brief.json").read_text())
    open_gaps = [g for g in brief["intake"]["gaps"]
                 if g["status"] == "open"]
    assert open_gaps  # something left to ping after the earlier answer

    ok = client.post("/api/pursuits/pur_ig/gate0",
                     json={"decision": "approved"})
    assert ok.status_code == 200, ok.text
    job = client.post("/api/pursuits/pur_ig/jobs",
                      json={"kind": "advance"}).json()
    assert "gate_1" in wait_job(client, job["id"])["message"]
    r = client.post("/api/pursuits/pur_ig/gate1",
                    json={"decision": "approved"})
    assert r.status_code == 200, r.text
    assert (ws / "pur_ig" / "brief.frozen.json").exists()

    r = client.post(
        f"/api/pursuits/pur_ig/gaps/{open_gaps[0]['gap_id']}/ping",
        json={"route_to": "sme"})
    assert r.status_code == 409
    assert "settled once the brief freezes" in r.json()["detail"]
