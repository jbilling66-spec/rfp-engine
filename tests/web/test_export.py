"""Export-to-Word (B37/D20) — the frozen clause "export opens in Word":
python-docx round-trips the output, the zip is structurally valid, the
prose is present; the blocked-refusal negative proves the submission
door never opens under a block; the two lanes live under their literal
headings and the download route is a closed allow-list, 403 anything
else."""

import io
import json
import zipfile

import pytest
from docx import Document
from fastapi.testclient import TestClient

from engine.web.server import create_app
from tests.validation.fixtures.validations import (
    make_validation_script,
    run_validation_package,
)
from tests.web.conftest import FIXED_AT, raising_caller, sign_in



@pytest.fixture(scope="module")
def exportable(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("web-export")
    pursuit, report, _ = run_validation_package(tmp)
    assert report.status == "complete"
    app = create_app(tmp, make_caller=raising_caller, now=lambda: FIXED_AT)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        sign_in(client, "Eddy Exporter")
        yield client, pursuit


def _assert_opens_in_word(payload: bytes, must_contain: str):
    # structural zip validity + the OOXML content-types manifest
    zf = zipfile.ZipFile(io.BytesIO(payload))
    assert zf.testzip() is None
    assert "[Content_Types].xml" in zf.namelist()
    # python-docx round-trip: the reader Word uses is the reader we use
    doc = Document(io.BytesIO(payload))
    text = "\n".join(p.text for p in doc.paragraphs)
    assert must_contain in text
    return text


def test_export_opens_in_word(exportable):
    client, pursuit = exportable
    pid = pursuit.pursuit_id
    r = client.post(f"/api/pursuits/{pid}/export", json={})
    assert r.status_code == 200, r.text
    lanes = r.json()
    assert set(lanes) == {"submission", "review", "bundle"}
    # the export door composes the bundle too (P18/C6 — one law at
    # every exit): the render produced, and the container's declared
    # workbook — absent from the inbox — is RECORDED absent
    by_lane = {d["lane"]: d for d in lanes["bundle"]["deliverables"]}
    assert by_lane["submission_render"]["status"] == "produced"
    assert by_lane["xlsx_writeback"]["status"] == "absent"
    envelope = pursuit.read_artifact("drafts/draft.json")
    prose = next(a["prose"] for e in envelope["sections"]
                 for a in e.get("answers", []) if a.get("prose"))
    sub = client.get(f"/api/pursuits/{pid}/download/response.docx")
    assert sub.status_code == 200
    sub_text = _assert_opens_in_word(sub.content, prose.split(".")[0])
    assert "Internal" not in sub_text  # the buyer copy carries no chrome
    rev = client.get(f"/api/pursuits/{pid}/download/annotated-review.docx")
    assert rev.status_code == 200
    rev_text = _assert_opens_in_word(rev.content, "Internal — do not send")
    assert "Packaging: clear" in rev_text
    # downloads list under the two literal headings
    listing = client.get(f"/api/pursuits/{pid}/downloads").json()
    assert listing["to_the_buyer"] == ["response.docx"]
    assert "annotated-review.docx" in listing["internal_do_not_send"]
    # the allow-list refuses everything else — never a general file server
    for name in ("plan.json", "../plan.json", "brief.json",
                 "events/events.jsonl"):
        assert client.get(
            f"/api/pursuits/{pid}/download/{name}").status_code in (403,
                                                                    404)
    # export artifact lines landed with revision_n
    runs = sorted((pursuit.root / "runs").glob("*/run.jsonl"))
    records = [json.loads(l) for l in runs[-1].read_text().splitlines()]
    exports = [x for x in records if x.get("record_type") == "artifact"
               and x["artifact"]["kind"] == "export"]
    assert len(exports) == 2


def test_blocked_packaging_refuses_submission_not_review(tmp_path):
    pursuit, report, _ = run_validation_package(
        tmp_path, script=make_validation_script(plant_unsupported=True))
    app = create_app(tmp_path, make_caller=raising_caller,
                     now=lambda: FIXED_AT)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        sign_in(client, "Eddy Exporter")
        pid = pursuit.pursuit_id
        r = client.post(f"/api/pursuits/{pid}/export", json={})
        assert r.status_code == 409
        assert "BLOCKED" in r.json()["detail"]
        assert not (pursuit.root / "exports" / "submission").exists() or \
            not list((pursuit.root / "exports" / "submission").iterdir())
        # the INTERNAL copy still renders — the reader needs the truth
        r = client.post(f"/api/pursuits/{pid}/export",
                        json={"lane": "review"})
        assert r.status_code == 200
        rev = client.get(f"/api/pursuits/{pid}/download/"
                         "annotated-review.docx")
        text = _assert_opens_in_word(rev.content, "Packaging: BLOCKED")
        assert "tier-1 block" in text


def test_export_refuses_tampered_frozen_brief(tmp_path):
    """P0-2 at the exit door: a frozen brief modified after Gate 1 (a raw
    write past the door) makes the submission AND review renders refuse
    with a 409 naming the verification, and the gate run records the
    failure — nothing buyer-facing is produced from an unvouched freeze."""
    pursuit, report, _ = run_validation_package(tmp_path)
    assert report.status == "complete"
    frozen = pursuit.root / "brief.frozen.json"
    frozen.write_text(frozen.read_text(encoding="utf-8").replace(
        '"name"', '"name "', 1), encoding="utf-8")
    app = create_app(tmp_path, make_caller=raising_caller,
                     now=lambda: FIXED_AT)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        sign_in(client, "Eddy Exporter")
        r = client.post(f"/api/pursuits/{pursuit.pursuit_id}/export",
                        json={"lane": "both"})
    assert r.status_code == 409
    assert "fails verification" in r.json()["detail"]
    assert not (pursuit.root / "exports" / "submission").exists() or not any(
        (pursuit.root / "exports" / "submission").iterdir())


def test_both_exit_doors_refuse_stale_bindings(tmp_path):
    """P0-16 at the exits: an envelope bound to another freeze refuses the
    write-back confirm door AND the export door; an annotated draft that
    no longer matches the envelope refuses the export — each 409 names
    the binding that broke, and nothing buyer-facing is produced."""
    pursuit, report, _ = run_validation_package(tmp_path)
    assert report.status == "complete"
    draft = pursuit.root / "drafts" / "draft.json"
    envelope = json.loads(draft.read_text(encoding="utf-8"))
    good = draft.read_bytes()
    app = create_app(tmp_path, make_caller=raising_caller,
                     now=lambda: FIXED_AT)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        sign_in(client, "Eddy Exporter")
        pid = pursuit.pursuit_id
        draft.write_text(json.dumps({**envelope, "plan_sha256": "0" * 64}),
                         encoding="utf-8")
        r = client.post(f"/api/pursuits/{pid}/writeback/confirm",
                        json={})
        assert r.status_code == 409 and "different frozen plan" in r.text
        r = client.post(f"/api/pursuits/{pid}/export",
                        json={"lane": "both"})
        assert r.status_code == 409 and "different frozen plan" in r.text
        draft.write_bytes(good)
        draft.write_text(draft.read_text(encoding="utf-8") + "\n",
                         encoding="utf-8")  # the envelope moved on
        r = client.post(f"/api/pursuits/{pid}/export",
                        json={"lane": "review"})
        assert r.status_code == 409 and "does not match" in r.text
    assert not (pursuit.root / "exports" / "submission").exists() or not any(
        (pursuit.root / "exports" / "submission").iterdir())
