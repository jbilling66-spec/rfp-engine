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


def test_the_listing_carries_each_buyer_files_hygiene(exportable):
    """W2b 5 (B136; P3-15 rendered): the downloads door hands the shell
    what each buyer file carries at the part level, from the bundle's own
    hygiene block — an additive sibling keyed by name, the wave-1 list
    untouched. The render lane's file is the proof here."""
    client, pursuit = exportable
    pid = pursuit.pursuit_id
    assert client.post(f"/api/pursuits/{pid}/export", json={}).status_code == 200
    listing = client.get(f"/api/pursuits/{pid}/downloads").json()
    assert listing["to_the_buyer"] == ["response.docx"]  # the shape stands
    line = listing["hygiene"]["response.docx"]
    assert set(line) == {"creator", "last_modified_by", "revision_marks",
                         "comment_parts", "firm_identity"}
    assert isinstance(line["revision_marks"], int)
    assert isinstance(line["comment_parts"], int)
    assert line["firm_identity"] in ("configured", "unconfigured")
    # the engine's own render carries no tracked changes and no comments
    assert line["revision_marks"] == 0 and line["comment_parts"] == 0


# --- P32a: the egress gate at the export door ------------------------------

OTHER_PROV = {"source_pursuit": "pur_other", "source_client":
              "Zephyrline Logistics", "date": "2025-02-02",
              "ingested_by": "ingestion_agent"}


def _index_identifier(tmp_path, kb_id: str, identifier: str) -> None:
    """Another client's card in the workspace's own store (the
    fixture-chain layout the app resolves first) — its identifier enters
    the restricted index the export scans against."""
    from engine.kb import KBStore
    KBStore(tmp_path / "kb").write_card(
        {"kb_id": kb_id, "layer": "corpus",
         "summary": "A section from [CLIENT]."},
        "Body from [CLIENT].", OTHER_PROV, {identifier: "CLIENT"})


def _last_run(pursuit) -> tuple[list[dict], dict]:
    runs = sorted((pursuit.root / "runs").glob("*/run.jsonl"))
    records = [json.loads(l) for l in runs[-1].read_text().splitlines()]
    lines = [r["validation"] for r in records
             if r.get("record_type") == "validation"]
    return lines, records[-1]


def test_the_submission_render_refuses_another_clients_identifier(tmp_path):
    """P32a (A6's pre-export scan, THREAT_MODEL T2): a phrase the
    restricted index holds for ANOTHER client sits in the drafted prose
    (the canonical block's own words) → the submission export refuses
    typed; nothing lands under exports/submission; the bundle names the
    render lane refused with locations and counts — never the phrase;
    the run log carries the block line and the failed footer; the
    internal review copy still renders (the reader needs the truth)."""
    pursuit, report, _ = run_validation_package(tmp_path)
    assert report.status == "complete"
    _index_identifier(tmp_path, "kb_other000001", "rehearsed cutover runbook")
    app = create_app(tmp_path, make_caller=raising_caller,
                     now=lambda: FIXED_AT)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        sign_in(client, "Eddy Exporter")
        pid = pursuit.pursuit_id
        r = client.post(f"/api/pursuits/{pid}/export", json={})
        assert r.status_code == 409, r.text
        detail = r.json()["detail"]
        assert "identifier residue at" in detail and ":answer:" in detail
        assert "rehearsed" not in detail and "cutover" not in detail
        sub = pursuit.root / "exports" / "submission"
        assert not sub.exists() or not any(sub.iterdir())
        listing = client.get(f"/api/pursuits/{pid}/downloads").json()
        assert listing["to_the_buyer"] == []
        refused = next(d for d in listing["refused"]
                       if d["name"] == "response.docx")
        assert refused["status"] == "refused"
        assert "identifier residue" in refused["reason"]
        assert "rehearsed" not in refused["reason"]
        assert client.get(
            f"/api/pursuits/{pid}/download/response.docx").status_code == 409
        lines, footer = _last_run(pursuit)
        assert {"check": "pre_export_leakage", "result": "block"} in lines
        assert footer["record_type"] == "run_end"
        assert footer["run"]["status"] == "failed"
        r = client.post(f"/api/pursuits/{pid}/export", json={"lane": "review"})
        assert r.status_code == 200, r.text


def test_this_buyers_own_name_in_the_index_is_not_residue(tmp_path):
    """The buyer's name belongs in its own proposal: indexed from an
    earlier ingest or not, it is subtracted from the universe, and the
    export produces with the scan's pass line on the run."""
    pursuit, report, _ = run_validation_package(tmp_path)
    assert report.status == "complete"
    _index_identifier(tmp_path, "kb_other000002", "Northwind Regional Health")
    app = create_app(tmp_path, make_caller=raising_caller,
                     now=lambda: FIXED_AT)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        sign_in(client, "Eddy Exporter")
        pid = pursuit.pursuit_id
        r = client.post(f"/api/pursuits/{pid}/export", json={})
        assert r.status_code == 200, r.text
        sub = client.get(f"/api/pursuits/{pid}/download/response.docx")
        _assert_opens_in_word(sub.content, "Northwind Regional Health")
    lines, footer = _last_run(pursuit)
    assert lines == [{"check": "pre_export_leakage", "result": "pass"}]
    assert footer["run"]["status"] == "completed"


def test_the_internal_review_copy_needs_the_operator(exportable):
    """P32a: the copy labelled "Internal — do not send" was served on an
    open GET — the one unguarded internal egress. It now needs the
    operator's session; the buyer lane stays an open read off the bundle
    record, as the shell's download links rely on."""
    client, pursuit = exportable
    pid = pursuit.pursuit_id
    assert client.post(f"/api/pursuits/{pid}/export", json={}).status_code == 200
    anonymous = TestClient(client.app, base_url="http://127.0.0.1")
    assert anonymous.get(
        f"/api/pursuits/{pid}/download/response.docx").status_code == 200
    assert anonymous.get(
        f"/api/pursuits/{pid}/download/annotated-review.docx").status_code == 401
    assert client.get(
        f"/api/pursuits/{pid}/download/annotated-review.docx").status_code == 200
