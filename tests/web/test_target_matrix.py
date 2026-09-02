"""The declared-target shape matrix over HTTP (P16/C9): a declared
DOCX target rides the whole pre-plan chain and NEVER falls to glob
order (the server.py:237 regression — an xlsx sits in the inbox as
bait), the forecast counts the docx slots, and the gate_0 screen flags
a declaration/inference contradiction pre-spend. FakeCaller default
app — dry_run, zero spend."""

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from engine.cli.slice import DEMO_PACK, DEMO_RAMBLE, DEMO_WORKBOOK
from engine.web.server import create_app
from tests.intake.fixtures.packages import FIXTURES as INTAKE_FIXTURES
from tests.web.conftest import FIXED_AT, sign_in, wait_job

ROLE = {"actor_role": "pursuit_lead"}
PDF_TWIN = INTAKE_FIXTURES / "pdf-twin.pdf"
OUTLINE_TWIN = Path(__file__).resolve().parents[1] / "fixtures" / "outline-twin.docx"


@pytest.fixture(scope="module")
def matrix_client(tmp_path_factory):
    ws = tmp_path_factory.mktemp("web-matrix") / "ws"
    app = create_app(ws, now=lambda: FIXED_AT)
    client = TestClient(app, base_url="http://127.0.0.1")
    client.__enter__()
    sign_in(client, "Max Matrix")
    yield client, ws
    client.__exit__(None, None, None)


def test_declared_docx_target_never_falls_to_glob_order(matrix_client):
    """Pre-P16, server.py's target filter was `.endswith('.xlsx')` — a
    declared DOCX target silently fell through to the first-glob xlsx.
    The supplemental workbook here is exactly that bait."""
    client, ws = matrix_client
    client.post("/api/pursuits", json={"pursuit_id": "pur_matrix"})
    client.put("/api/pursuits/pur_matrix/inbox/rfp-core.pdf",
               params={"role": "core"}, content=PDF_TWIN.read_bytes())
    client.put("/api/pursuits/pur_matrix/inbox/response-outline.docx",
               params={"role": "target"},
               content=OUTLINE_TWIN.read_bytes())
    client.put("/api/pursuits/pur_matrix/inbox/pricing-bait.xlsx",
               params={"role": "supplemental"},
               content=DEMO_WORKBOOK.read_bytes())
    for name, path in (("ramble.md", DEMO_RAMBLE),
                       ("research-pack.md", DEMO_PACK)):
        client.put(f"/api/pursuits/pur_matrix/inbox/{name}",
                   content=path.read_bytes())

    job = client.post("/api/pursuits/pur_matrix/jobs",
                      json={"kind": "advance"}).json()
    assert "gate_0" in wait_job(client, job["id"])["message"]

    model = client.get("/api/pursuits/pur_matrix/gate0").json()
    assert model["target_conflicts"] == []  # declared docx + designated
    fc = model["forecast"]
    assert (fc["unit"], fc["unit_count"]) == ("target_slots", 6)

    assert client.post("/api/pursuits/pur_matrix/gate0",
                       json={"decision": "approved"}).status_code == 200
    job = client.post("/api/pursuits/pur_matrix/jobs",
                      json={"kind": "advance"}).json()
    assert "gate_1" in wait_job(client, job["id"])["message"]
    assert client.post("/api/pursuits/pur_matrix/gate1",
                       json={"decision": "approved",
                             **ROLE}).status_code == 200
    job = client.post("/api/pursuits/pur_matrix/jobs",
                      json={"kind": "advance"}).json()
    assert "gate_2" in wait_job(client, job["id"])["message"]

    slots = json.loads((ws / "pur_matrix" / "slots.json").read_text())
    assert slots["source_sha256"] == hashlib.sha256(
        OUTLINE_TWIN.read_bytes()).hexdigest()  # the DOCX, not the bait
    assert slots["source_mode"] == "client_provided"
    plan = json.loads((ws / "pur_matrix" / "plan.json").read_text())
    assert "Executive Summary" in [s["title"] for s in plan["sections"]]
    # Gate 2's read model shows slot-bearing sections for the docx shape
    g2 = client.get("/api/pursuits/pur_matrix/gate2").json()
    assert any(s.get("slot_count", 0) > 0 for s in g2["sections"])


def test_gate0_flags_designated_without_a_declared_target(matrix_client):
    """The intake model says designated but no document carries
    role=target — the contradiction shows on the gate_0 screen where
    the register correction fixes it, BEFORE any spend."""
    client, ws = matrix_client
    client.post("/api/pursuits", json={"pursuit_id": "pur_conflict"})
    client.put("/api/pursuits/pur_conflict/inbox/rfp-core.pdf",
               params={"role": "core"}, content=PDF_TWIN.read_bytes())
    client.put("/api/pursuits/pur_conflict/inbox/ramble.md",
               content=DEMO_RAMBLE.read_bytes())
    job = client.post("/api/pursuits/pur_conflict/jobs",
                      json={"kind": "advance"}).json()
    assert "gate_0" in wait_job(client, job["id"])["message"]
    model = client.get("/api/pursuits/pur_conflict/gate0").json()
    assert any("no document is declared role=target" in c
               for c in model["target_conflicts"])
