"""The P2-29a regression test P25 item 8 shipped without (P26a Group B):
an envelope that somehow carries a control character — planted RAW here,
past every entry-side refusal — makes both exit doors answer a typed
409 with the run CLOSED (footer status failed), never a 500 over a
footerless run. Its own module: the fixture is mutated on purpose."""

import json

import pytest
from fastapi.testclient import TestClient

from engine.runlog import read_run
from engine.web.server import create_app
from tests.helpers import plant_annotated
from tests.validation.fixtures.validations import run_validation_package
from tests.web.conftest import FIXED_AT, raising_caller, sign_in

ROLE = {"actor_role": "pursuit_lead"}


@pytest.fixture(scope="module")
def poisoned(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("web-export-ctrl")
    pursuit, report, _ = run_validation_package(tmp)
    assert report.status == "complete"
    path = pursuit.root / "drafts" / "draft.json"
    envelope = json.loads(path.read_text(encoding="utf-8"))
    section = next(s for s in envelope["sections"] if s["status"] == "drafted")
    target = section["answers"][0] if section.get("answers") else section
    target["prose"] = (target.get("prose") or "") + " bad\x0bchar"
    path.write_text(json.dumps(envelope), encoding="utf-8")  # RAW, on purpose
    plant_annotated(pursuit)  # rebind the annotation to the poisoned bytes
    app = create_app(tmp, make_caller=raising_caller, now=lambda: FIXED_AT)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        sign_in(client, "Cara Control")
        yield client, pursuit


def _last_run_footer(pursuit):
    runs = sorted((pursuit.root / "runs").glob("run_*/run.jsonl"))
    records = read_run(runs[-1])
    return records[-1]


def test_export_door_refuses_typed_and_closes_the_run(poisoned):
    client, pursuit = poisoned
    r = client.post(f"/api/pursuits/{pursuit.pursuit_id}/export",
                    json={**ROLE})
    assert r.status_code == 409, r.text
    assert "XML compatible" in r.json()["detail"]
    footer = _last_run_footer(pursuit)
    assert footer["record_type"] == "run_end"
    assert footer["run"]["status"] == "failed"
