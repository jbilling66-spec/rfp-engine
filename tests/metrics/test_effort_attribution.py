"""P27 wave 1 (M-9), the acceptance's attribution proof: the effort a
session records is priced at the SESSION's role — a partner-hour costs
the partner rate, an SME-hour the SME rate — and a client cannot name a
role on the payload. Every expected value below is computed BY HAND from
config/rates.yaml (partner 385, sme 240, contracts 165 — synthetic-v0),
never pasted from a run."""

from fastapi.testclient import TestClient

from engine.cli.slice import DEMO_PACK, DEMO_RAMBLE, DEMO_WORKBOOK
from engine.metrics.resolver import Corpus, load_rates, resolve
from engine.web.server import create_app
from tests.web.conftest import FIXED_AT, raising_caller, sign_in, wait_job


def test_rates_pin_the_hand_computation():
    roles = load_rates()["roles"]
    assert (roles["partner"], roles["sme"], roles["contracts"]) == (
        385.0, 240.0, 165.0)


def test_effort_is_priced_at_the_session_role(tmp_path):
    ws = tmp_path / "ws"
    app = create_app(ws, make_caller=raising_caller, now=lambda: FIXED_AT)
    with TestClient(app, base_url="http://127.0.0.1") as partner:
        sign_in(partner, "Pat Partner", role="partner")
        partner.post("/api/pursuits", json={"pursuit_id": "pur_cost"})
        r = partner.post("/api/pursuits/pur_cost/effort", json={
            "measurement": "manual", "confirmed_minutes": 60})
        assert r.status_code == 200, r.text
        # a second person, a second session, a second role
        sme = TestClient(app, base_url="http://127.0.0.1")
        sign_in(sme, "Sky Sme", role="sme")
        r = sme.post("/api/pursuits/pur_cost/effort", json={
            "measurement": "manual", "confirmed_minutes": 30})
        assert r.status_code == 200, r.text
        # a payload role is refused — nothing lands
        r = sme.post("/api/pursuits/pur_cost/effort", json={
            "measurement": "manual", "confirmed_minutes": 30,
            "actor_role": "partner"})
        assert r.status_code == 422
    corpus = Corpus(ws)
    hours = resolve("reviewer_hours_per_proposal", corpus)
    assert hours["value"] == 1.5 and hours["n"] == 1        # 90 min / 1
    cost = resolve("human_cost_per_proposal", corpus)
    assert cost["value"] == 385.0 + 120.0                    # 1h@385 + .5h@240
    # one pursuit is below the registry's min_n: the figure renders as a
    # COUNT, never a stated rate — the attribution is what this proves
    assert cost["n"] == 1 and cost["status"] == "count_only"


def test_a_gate_decision_carries_effort_at_the_session_role(tmp_path):
    """The producer's path: a gate decision with {active_ms,
    confirmed_minutes} lands a review_session priced at the deciding
    session's role (contracts, 30 min → 82.5)."""
    ws = tmp_path / "ws"
    app = create_app(ws, now=lambda: FIXED_AT)  # FakeCaller: zero spend
    with TestClient(app, base_url="http://127.0.0.1") as client:
        sign_in(client, "Cam Contracts", role="contracts")
        client.post("/api/pursuits", json={"pursuit_id": "pur_gate"})
        for name, path in (("demo-twin.xlsx", DEMO_WORKBOOK),
                           ("ramble.md", DEMO_RAMBLE),
                           ("research-pack.md", DEMO_PACK)):
            client.put(f"/api/pursuits/pur_gate/inbox/{name}",
                       content=path.read_bytes())
        job = client.post("/api/pursuits/pur_gate/jobs",
                          json={"kind": "advance"}).json()
        assert "gate_0" in wait_job(client, job["id"])["message"]
        r = client.post("/api/pursuits/pur_gate/gate0", json={
            "decision": "approved",
            "effort": {"active_ms": 1_800_000, "confirmed_minutes": 30}})
        assert r.status_code == 200, r.text
    cost = resolve("human_cost_per_proposal", Corpus(ws))
    assert cost["value"] == 82.5                              # .5h @ 165
