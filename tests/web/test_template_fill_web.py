"""The firm_default lane over HTTP (P17/C10): the writeback dispatcher
reads the container's OWN source_mode (a firm-template pursuit no longer
dies inside the buyer-docx resolver), preview→confirm fills the
template, the filled response.docx is the one to-the-buyer download,
and the generated render REFUSES firm_default with the pointer (B75§1d —
one submission document per pursuit)."""

import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from engine.planning.plan import REFERENCE_DEFAULT
from engine.structure import merge_parsed, parse_default_template
from engine.web.server import create_app
from engine.workspace import PursuitDir
from tests.web.conftest import FIXED_AT, sign_in
from tests.helpers import plant_annotated, plant_freeze

PARA = "A synthetic executive summary paragraph."


@pytest.fixture(scope="module")
def fill_client(tmp_path_factory):
    ws = tmp_path_factory.mktemp("web-fill") / "ws"
    app = create_app(ws, now=lambda: FIXED_AT)
    client = TestClient(app, base_url="http://127.0.0.1")
    client.__enter__()
    sign_in(client, "Fiona Filler")
    client.post("/api/pursuits", json={"pursuit_id": "pur_fill"})
    pursuit = PursuitDir(ws, "pur_fill")
    parsed = parse_default_template(REFERENCE_DEFAULT)
    container = {"pursuit_id": "pur_fill", **merge_parsed([parsed])}
    pursuit.write_artifact("target_slots", container, name="slots.json")
    pursuit.checkpoint("path_b_outline", {
        "reference_sha256": hashlib.sha256(
            REFERENCE_DEFAULT.read_bytes()).hexdigest()})
    plant_freeze(pursuit, "pursuit_plan", {
        "pursuit_id": "pur_fill", "path": "B_free_flow",
        "slots_ref": "slots.json", "status": "approved",
        "sections": [{"section_id": "sec-exec",
                      "slot_ids": ["s-h02-hdr", "s-h02"]}]})
    (pursuit.root / "drafts" / "draft.json").write_text(json.dumps({
        "plan_sha256": pursuit.file_sha256("plan.frozen.json"), "revision_n": 0,
        "sections": [{"section_id": "sec-exec", "status": "drafted",
                      "prose": PARA}]}))
    plant_annotated(pursuit)
    yield client, ws
    client.__exit__(None, None, None)


def test_preview_confirm_fill_and_download(fill_client):
    client, ws = fill_client
    body = client.get(
        "/api/pursuits/pur_fill/writeback/preview").json()
    preview = body["files"][0]  # the uniform shape (P18/C6, B77§2 D4)
    decisions = {r["slot_id"]: r["decision"]
                 for r in preview["sections"]}
    assert decisions["s-h02"] == "filled"
    assert preview["confirmed_by"] == "(unconfirmed)"

    facts = client.post("/api/pursuits/pur_fill/writeback/confirm",
                        json={"at": FIXED_AT})
    assert facts.status_code == 200, facts.text
    confirmed = facts.json()
    out = confirmed["files"][0]
    assert out["confirmed_by"] == "Fiona Filler"
    assert out["output_file"] == "exports/submission/response.docx"
    # the firm_default bundle is ONE entry: the filled template IS the
    # to-the-buyer set (B75§1d), no submission_render twin
    deliverables = confirmed["bundle"]["deliverables"]
    assert [d["lane"] for d in deliverables] == ["template_fill"]
    assert deliverables[0]["status"] == "produced"
    assert deliverables[0]["facts_path"] == "exports/template-fill-facts.json"
    assert (ws / "pur_fill" / "exports" / "submission" /
            "response.docx").exists()
    assert (ws / "pur_fill" / "exports" /
            "template-fill-facts.json").exists()

    downloads = client.get("/api/pursuits/pur_fill/downloads").json()
    assert "response.docx" in downloads["to_the_buyer"]
    got = client.get("/api/pursuits/pur_fill/download/response.docx")
    assert got.status_code == 200


def test_generated_render_refuses_firm_default_with_the_pointer(
        fill_client):
    client, _ws = fill_client
    resp = client.post("/api/pursuits/pur_fill/export",
                       json={"lane": "submission", "at": FIXED_AT})
    assert resp.status_code == 409
    assert "FILLED template" in resp.json()["detail"]
