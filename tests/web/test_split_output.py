"""THE P18 acceptance surface: a pursuit whose declared target set needs
BOTH an xlsx form and a docx questionnaire gets BOTH write-back lanes
through one confirm — per-file facts records with no filename collision,
a submission bundle enumerating every deliverable with digests and
decision-record paths, refusals RECORDED while the other lane produces,
and 409-with-no-bundle only when every lane refuses.
"""

import hashlib
import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from engine.structure import merge_parsed, parse_buyer_docx, parse_workbook
from engine.web.server import create_app
from engine.workspace import PursuitDir
from tests.web.conftest import FIXED_AT, raising_caller, sign_in
from tests.helpers import plant_annotated, plant_freeze

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
PROSE = "Cutover completes inside the rehearsal-validated window."


@pytest.fixture()
def split(tmp_path):
    """qform-twin.docx (f00) + demo-twin.xlsx (f01) declared together —
    the exact pursuit shape the P18 row names; one prose slot drafted on
    EACH file."""
    ws = tmp_path / "ws"
    pursuit = PursuitDir(ws, "pur_split")
    inbox = pursuit.root / "inbox"
    shutil.copy2(FIXTURES / "qform-twin.docx", inbox / "qform-twin.docx")
    shutil.copy2(FIXTURES / "demo-twin.xlsx", inbox / "demo-twin.xlsx")
    parsed = [parse_buyer_docx(inbox / "qform-twin.docx"),
              parse_workbook(inbox / "demo-twin.xlsx")]
    container = {"pursuit_id": "pur_split", **merge_parsed(parsed)}
    pursuit.write_artifact("target_slots", container, name="slots.json")
    planned = [s["slot_id"] for s in container["slots"]
               if not s.get("is_header")]
    plant_freeze(pursuit, "pursuit_plan", {
        "pursuit_id": "pur_split", "path": "A_designated",
        "slots_ref": "slots.json", "status": "approved",
        "sections": [{"section_id": "all", "slot_ids": planned}],
    })
    (pursuit.root / "drafts").mkdir(exist_ok=True)
    (pursuit.root / "drafts" / "draft.json").write_text(json.dumps({
        "plan_sha256": pursuit.file_sha256("plan.frozen.json"), "revision_n": 1,
        "sections": [{"section_id": "all", "answers": [
            {"slot_id": "f00-s-t00-r01", "status": "drafted",
             "prose": PROSE},
            {"slot_id": "f01-slot_01_r002", "status": "drafted",
             "prose": PROSE},
        ]}],
    }), encoding="utf-8")
    plant_annotated(pursuit)
    app = create_app(ws, make_caller=raising_caller, now=lambda: FIXED_AT)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        sign_in(client, "Sam Splitter")
        yield client, pursuit


def test_split_output_set_gets_both_lanes(split):
    client, pursuit = split
    body = client.get("/api/pursuits/pur_split/writeback/preview").json()
    assert len(body["files"]) == 2 and body["refused"] == []
    r = client.post("/api/pursuits/pur_split/writeback/confirm",
                    json={"at": FIXED_AT})
    assert r.status_code == 200, r.text
    confirmed = r.json()
    assert len(confirmed["files"]) == 2
    # per-file facts records, no filename collision (the recorded
    # blockers: FACTS_NAME constants and output_file singulars)
    facts_paths = {f_["output_file"] for f_ in confirmed["files"]}
    assert facts_paths == {"exports/writeback/qform-twin.docx",
                           "exports/writeback/demo-twin.xlsx"}
    for name in ("exports/docx-writeback-facts-f00.json",
                 "exports/writeback-facts-f01.json"):
        assert (pursuit.root / name).is_file(), name
    # the bundle enumerates EVERY to-the-buyer deliverable with digests
    # and decision-record paths
    deliverables = confirmed["bundle"]["deliverables"]
    by_lane = {d["lane"]: d for d in deliverables}
    assert set(by_lane) == {"docx_writeback", "xlsx_writeback",
                            "submission_render"}
    for lane in ("docx_writeback", "xlsx_writeback"):
        entry = by_lane[lane]
        assert entry["status"] == "produced"
        on_disk = pursuit.root / entry["path"]
        assert entry["sha256"] == hashlib.sha256(
            on_disk.read_bytes()).hexdigest()
        assert (pursuit.root / entry["facts_path"]).is_file()
    # the render half has not run: recorded absent, never omitted
    assert by_lane["submission_render"]["status"] == "absent"
    # and the record is on disk, schema-validated at write
    stored = pursuit.read_artifact("exports/submission-bundle.json")
    assert stored["deliverables"] == deliverables


def test_refused_lane_recorded_while_the_other_produces(split):
    client, pursuit = split
    (pursuit.root / "inbox" / "demo-twin.xlsx").write_bytes(b"tampered")
    r = client.post("/api/pursuits/pur_split/writeback/confirm",
                    json={"at": FIXED_AT})
    assert r.status_code == 200, r.text  # one deliverable DID produce
    confirmed = r.json()
    assert len(confirmed["files"]) == 1
    by_lane = {d["lane"]: d for d in confirmed["bundle"]["deliverables"]}
    assert by_lane["docx_writeback"]["status"] == "produced"
    refused = by_lane["xlsx_writeback"]
    assert refused["status"] == "refused"
    assert "source_sha256" in refused["reason"]


def test_every_lane_refused_is_409_and_no_bundle(split):
    client, pursuit = split
    (pursuit.root / "inbox" / "demo-twin.xlsx").write_bytes(b"tampered")
    (pursuit.root / "inbox" / "qform-twin.docx").write_bytes(b"tampered")
    r = client.post("/api/pursuits/pur_split/writeback/confirm",
                    json={"at": FIXED_AT})
    assert r.status_code == 409
    assert not (pursuit.root / "exports"
                / "submission-bundle.json").exists()


def test_downloads_read_the_bundle_not_the_directory(split):
    """THE downloads law (P18/C7, B77§2 D6): the buyer listing is the
    bundle's produced entries; a file planted in the submission folder
    that no record vouches for is neither listed nor served — v1's
    unshippable-file weakness, banned."""
    client, pursuit = split
    r = client.post("/api/pursuits/pur_split/writeback/confirm",
                    json={"at": FIXED_AT})
    assert r.status_code == 200, r.text
    rogue = pursuit.root / "exports" / "submission" / "rogue.docx"
    rogue.parent.mkdir(parents=True, exist_ok=True)
    rogue.write_bytes(b"nobody vouched for this")
    listing = client.get("/api/pursuits/pur_split/downloads").json()
    # filled buyer forms ARE buyer deliverables (B77§1a) — they list
    # under the buyer heading; the un-produced render does not
    assert listing["to_the_buyer"] == ["demo-twin.xlsx",
                                       "qform-twin.docx"]
    assert "rogue.docx" not in listing["to_the_buyer"]
    assert all("writeback/" not in n
               for n in listing["internal_do_not_send"])
    # served by the RECORD's path, refused where no record vouches
    for name in ("demo-twin.xlsx", "qform-twin.docx"):
        assert client.get(
            f"/api/pursuits/pur_split/download/{name}").status_code == 200
    assert client.get(
        "/api/pursuits/pur_split/download/rogue.docx").status_code == 404


def test_no_bundle_means_an_empty_buyer_list(split):
    client, pursuit = split
    # nothing confirmed, nothing composed: an honest nothing-shippable,
    # even though preview works and the inbox is full
    assert client.get(
        "/api/pursuits/pur_split/writeback/preview").status_code == 200
    listing = client.get("/api/pursuits/pur_split/downloads").json()
    assert listing["to_the_buyer"] == []
