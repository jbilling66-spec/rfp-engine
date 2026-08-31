"""The ping-lane gap-answer→proposed-card link (P17/C11, B72§5's
deferral closed): a ping answer may OPT IN to spawning a new_card
proposal through the steward door — exactly gate_0's link (B69§7),
extended to the second answer path. Never automatic, never straight
into the corpus, and a request that cannot be honored refuses BEFORE
anything mutates."""

import json

import pytest
from fastapi.testclient import TestClient

from engine.flywheel.proposals import ProposalStore
from engine.kb.store import KBStore
from engine.web.pings import PingError, PingLane
from engine.web.server import create_app
from engine.workspace import PursuitDir
from tests.web.conftest import FIXED_AT, sign_in

PLAN = {
    "pursuit_id": "pur_pingcard", "path": "A_designated",
    "status": "approved",
    "sections": [{
        "section_id": "sec-01", "title": "Approach",
        "gaps": [
            {"gap_id": "gap_pc_001", "slot_id": "s-a01", "kind": "no_content",
             "status": "open",
             "question_to_human": "What is our data-conversion stance?"},
            {"gap_id": "gap_pc_002", "slot_id": "s-a02", "kind": "no_content",
             "status": "open",
             "question_to_human": "What is our training stance?"},
        ]}],
}


@pytest.fixture(scope="module")
def ping_client(tmp_path_factory):
    ws = tmp_path_factory.mktemp("web-pingcard") / "ws"
    (ws / "kb").mkdir(parents=True)  # the app's kb_root → this workspace
    KBStore(ws / "kb")
    app = create_app(ws, now=lambda: FIXED_AT)
    client = TestClient(app)
    client.__enter__()
    sign_in(client, "Astrid Answerer")
    client.post("/api/pursuits", json={"pursuit_id": "pur_pingcard"})
    (ws / "pur_pingcard" / "plan.json").write_text(json.dumps(PLAN))
    yield client, ws
    client.__exit__(None, None, None)


def _ping(client, gap_id):
    r = client.post(f"/api/pursuits/pur_pingcard/gaps/{gap_id}/ping",
                    json={"route_to": "sme", "at": FIXED_AT})
    assert r.status_code == 200, r.text
    return r.json()["ping_id"]


def test_opt_in_answer_spawns_a_steward_proposal(ping_client):
    client, ws = ping_client
    plan = json.loads((ws / "pur_pingcard" / "plan.json").read_text())
    gap_id = plan["sections"][0]["gaps"][0]["gap_id"]
    ping_id = _ping(client, gap_id)
    r = client.post(
        f"/api/pursuits/pur_pingcard/pings/{ping_id}/answer",
        json={"answer": "We convert in four validated waves.",
              "propose_card": True, "at": FIXED_AT})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["proposal"].startswith("prop_")
    proposals = ProposalStore(ws / "kb").list(status="proposed")
    mine = [p for p in proposals
            if p["proposal_id"] == out["proposal"]]
    assert mine and mine[0]["source"]["door"] == "gap_answer"
    assert mine[0]["source"]["pursuit_id"] == "pur_pingcard"
    assert mine[0]["kind"] == "new_card"
    # steward inbox, NOT corpus: nothing entered the store.
    assert KBStore(ws / "kb").list_cards() == []


def test_plain_answer_spawns_nothing(ping_client):
    client, ws = ping_client
    plan = json.loads((ws / "pur_pingcard" / "plan.json").read_text())
    gap_id = plan["sections"][0]["gaps"][1]["gap_id"]
    before = len(ProposalStore(ws / "kb").list())
    ping_id = _ping(client, gap_id)
    r = client.post(
        f"/api/pursuits/pur_pingcard/pings/{ping_id}/answer",
        json={"answer": "Training is train-the-trainer.",
              "at": FIXED_AT})
    assert r.status_code == 200
    assert "proposal" not in r.json()
    assert len(ProposalStore(ws / "kb").list()) == before


def test_unwired_kb_root_refuses_before_mutating(tmp_path):
    pursuit = PursuitDir(tmp_path, "pur_bare")
    plan = json.loads(json.dumps(PLAN))
    lane = PingLane(pursuit)

    class _Sink:
        def emit(self, *a, **k):
            return 0

    record = lane.ping(_Sink(), plan, gap_id="gap_pc_001", route_to="sme",
                       at=FIXED_AT, actor="Astrid")
    with pytest.raises(PingError, match="never dropped"):
        lane.answer(_Sink(), plan, ping_id=record["ping_id"],
                    answer="an answer", at=FIXED_AT, actor="Astrid",
                    propose_card=True, kb_root=None)
    gap = plan["sections"][0]["gaps"][0]
    assert gap["status"] == "pinged", "the refusal mutated nothing"
