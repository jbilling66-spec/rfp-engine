"""P2-30 (P26b-1, B112), the door half: a buyer docx whose table is
ragged reaches write-back as a typed lane refusal on PREVIEW and on
CONFIRM — never a 500. The container is derived from the intact twin,
then the inbox file is replaced by a ragged copy and the container's
digest re-bound to it, so the binding check passes and the re-derivation
(`question_cell_map`) is what refuses."""

import hashlib
import json
import shutil
from pathlib import Path

import pytest
from docx import Document
from docx.oxml.ns import qn
from fastapi.testclient import TestClient

from engine.structure import merge_parsed, parse_buyer_docx
from engine.web.server import create_app
from engine.workspace import PursuitDir
from tests.helpers import plant_annotated, plant_freeze
from tests.web.conftest import FIXED_AT, raising_caller, sign_in

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture()
def ragged(tmp_path):
    ws = tmp_path / "ws"
    pursuit = PursuitDir(ws, "pur_rag")
    inbox = pursuit.root / "inbox"
    intact = inbox / "qform-twin.docx"
    shutil.copy2(FIXTURES / "qform-twin.docx", intact)
    parsed = parse_buyer_docx(intact)
    # Make table 0's second body row one cell short, in place.
    doc = Document(str(intact))
    tr = doc.tables[0].rows[2]._tr
    tr.remove(tr.findall(qn("w:tc"))[-1])
    doc.save(intact)
    container = {"pursuit_id": "pur_rag", **merge_parsed([parsed])}
    container["source_sha256"] = hashlib.sha256(intact.read_bytes()).hexdigest()
    pursuit.write_artifact("target_slots", container, name="slots.json")
    planned = [s["slot_id"] for s in container["slots"] if not s.get("is_header")]
    plant_freeze(pursuit, "pursuit_plan", {
        "pursuit_id": "pur_rag", "path": "A_designated",
        "slots_ref": "slots.json", "status": "approved",
        "sections": [{"section_id": "all", "slot_ids": planned}],
    })
    (pursuit.root / "drafts").mkdir(exist_ok=True)
    (pursuit.root / "drafts" / "draft.json").write_text(json.dumps({
        "plan_sha256": pursuit.file_sha256("plan.frozen.json"), "revision_n": 1,
        "sections": [{"section_id": "all", "answers": [
            {"slot_id": "s-t00-r01", "status": "drafted", "prose": "Answer."},
        ]}],
    }), encoding="utf-8")
    plant_annotated(pursuit)
    app = create_app(ws, make_caller=raising_caller, now=lambda: FIXED_AT)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        sign_in(client, "Rae Ragged")
        yield client


def test_preview_and_confirm_refuse_typed_never_500(ragged):
    r = ragged.get("/api/pursuits/pur_rag/writeback/preview")
    assert r.status_code == 409, r.text
    assert "ragged" in r.json()["detail"] and "table 0 row 2" in r.json()["detail"]
    r = ragged.post("/api/pursuits/pur_rag/writeback/confirm", json={})
    assert r.status_code != 500
    assert "ragged" in r.text
