"""Document roles on the inbox (P15/B67 §3): core / supplemental /
target are DECLARED at upload, never inferred — the target sometimes
arrives as an attachment, so nothing about a file says what it is. An
undeclared inbox keeps the legacy first-workbook behavior; a declared
one intakes every readable document and routes the target to planning.
FakeCaller default app — dry_run, zero spend."""

import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from engine.cli.slice import DEMO_PACK, DEMO_RAMBLE, DEMO_WORKBOOK
from engine.web.server import create_app
from tests.intake.fixtures.packages import FIXTURES
from tests.web.conftest import FIXED_AT, sign_in, wait_job

ROLE = {"actor_role": "pursuit_lead"}
PDF_TWIN = FIXTURES / "pdf-twin.pdf"


@pytest.fixture(scope="module")
def role_client(tmp_path_factory):
    ws = tmp_path_factory.mktemp("web-roles") / "ws"
    app = create_app(ws, now=lambda: FIXED_AT)
    client = TestClient(app, base_url="http://127.0.0.1")
    client.__enter__()
    sign_in(client, "Rae Roles")
    yield client, ws
    client.__exit__(None, None, None)


def test_role_declares_at_upload_and_persists(role_client):
    client, ws = role_client
    client.post("/api/pursuits", json={"pursuit_id": "pur_roles"})
    r = client.put("/api/pursuits/pur_roles/inbox/rfp-core.pdf",
                   params={"role": "core"}, content=PDF_TWIN.read_bytes())
    assert r.status_code == 200 and r.json()["role"] == "core"
    r = client.put("/api/pursuits/pur_roles/inbox/response-form.xlsx",
                   params={"role": "target"},
                   content=DEMO_WORKBOOK.read_bytes())
    assert r.status_code == 200
    # an out-of-vocab role refuses loudly — declared, never guessed
    bad = client.put("/api/pursuits/pur_roles/inbox/x.pdf",
                     params={"role": "main"}, content=b"x")
    assert bad.status_code == 422
    for name, path in (("ramble.md", DEMO_RAMBLE),
                       ("research-pack.md", DEMO_PACK)):
        client.put(f"/api/pursuits/pur_roles/inbox/{name}",
                   content=path.read_bytes())
    roles = json.loads((ws / "pur_roles" / "inbox" / "roles.json")
                       .read_text())
    assert roles == {"rfp-core.pdf": "core", "response-form.xlsx": "target"}


def test_declared_set_intakes_all_docs_and_routes_the_target(role_client):
    client, ws = role_client
    job = client.post("/api/pursuits/pur_roles/jobs",
                      json={"kind": "advance", "at": FIXED_AT}).json()
    assert "gate_0" in wait_job(client, job["id"])["message"]
    brief = json.loads((ws / "pur_roles" / "brief.json").read_text())
    docs = {d["file"]: d for d in brief["intake"]["documents"]}
    assert docs["rfp-core.pdf"]["role"] == "core"
    assert docs["rfp-core.pdf"]["kind"] == "rfp_main"
    assert docs["response-form.xlsx"]["role"] == "target"
    assert docs["response-form.xlsx"]["kind"] == "other"

    # the pre-flight forecast (C9) counts the DECLARED target's slots —
    # the demo twin's golden 19 — and labels itself an estimate
    model = client.get("/api/pursuits/pur_roles/gate0").json()
    fc = model["forecast"]
    assert fc["basis"] == "estimate"
    assert (fc["unit"], fc["unit_count"]) == ("target_slots", 19)
    assert fc["cost_usd_estimate"] > 0

    ok = client.post("/api/pursuits/pur_roles/gate0",
                     json={"decision": "approved", "at": FIXED_AT})
    assert ok.status_code == 200, ok.text
    job = client.post("/api/pursuits/pur_roles/jobs",
                      json={"kind": "advance", "at": FIXED_AT}).json()
    assert "gate_1" in wait_job(client, job["id"])["message"]
    r = client.post("/api/pursuits/pur_roles/gate1",
                    json={"decision": "approved", "at": FIXED_AT, **ROLE})
    assert r.status_code == 200, r.text
    job = client.post("/api/pursuits/pur_roles/jobs",
                      json={"kind": "advance", "at": FIXED_AT}).json()
    assert "gate_2" in wait_job(client, job["id"])["message"]
    # planning parsed the DECLARED target, not an accident of glob order —
    # slots.json records the source workbook's own digest
    slots = json.loads((ws / "pur_roles" / "slots.json").read_text())
    assert slots["source_sha256"] == hashlib.sha256(
        DEMO_WORKBOOK.read_bytes()).hexdigest()


def test_declared_set_without_a_core_refuses(role_client):
    client, ws = role_client
    client.post("/api/pursuits", json={"pursuit_id": "pur_nocore"})
    client.put("/api/pursuits/pur_nocore/inbox/form.xlsx",
               params={"role": "target"},
               content=DEMO_WORKBOOK.read_bytes())
    job = client.post("/api/pursuits/pur_nocore/jobs",
                      json={"kind": "advance", "at": FIXED_AT}).json()
    done = wait_job(client, job["id"])
    assert done["state"] == "refused"
    assert "role=core" in done["message"]
