"""P1-42 (P27 wave 1, register §5.9): a gate-0 decision carrying effort
must land its review_session. Before the schema commit the effort
`gate` enum had no `gate_0`, so the append — which runs AFTER the
decision commits — was refused over an already-decided gate: the
P25-item-1 failure mode through a door P25 never exercised. This test
was red against `7682383` and went green on the one-line enum change."""

import json

from fastapi.testclient import TestClient

from engine.cli.slice import DEMO_PACK, DEMO_RAMBLE, DEMO_WORKBOOK
from engine.web.server import create_app
from tests.web.conftest import FIXED_AT, sign_in, wait_job


def test_gate0_decision_with_effort_lands_its_review_session(tmp_path):
    ws = tmp_path / "ws"
    app = create_app(ws, now=lambda: FIXED_AT)  # FakeCaller: zero spend
    with TestClient(app, base_url="http://127.0.0.1") as client:
        sign_in(client, "Gale Gatekeeper", role="proposal_manager")
        client.post("/api/pursuits", json={"pursuit_id": "pur_g0"})
        for name, path in (("demo-twin.xlsx", DEMO_WORKBOOK),
                           ("ramble.md", DEMO_RAMBLE),
                           ("research-pack.md", DEMO_PACK)):
            client.put(f"/api/pursuits/pur_g0/inbox/{name}",
                       content=path.read_bytes())
        job = client.post("/api/pursuits/pur_g0/jobs",
                          json={"kind": "advance"}).json()
        done = wait_job(client, job["id"])
        assert "gate_0" in done["message"], done
        r = client.post("/api/pursuits/pur_g0/gate0", json={
            "decision": "approved",
            "effort": {"active_ms": 90000, "confirmed_minutes": 2}})
        assert r.status_code == 200, r.text
        events = [json.loads(l) for l in
                  (ws / "pur_g0" / "events" / "events.jsonl")
                  .read_text(encoding="utf-8").splitlines()]
        sessions = [e for e in events if e["kind"] == "review_session"]
        assert len(sessions) == 1
        assert sessions[0]["effort"]["gate"] == "gate_0"
        assert sessions[0]["effort"]["scope"] == "gate"
        assert sessions[0]["actor_role"] == "proposal_manager"
