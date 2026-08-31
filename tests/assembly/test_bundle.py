"""The submission bundle composer (P18/C3, B77§2 D2-D3): the expected
set derives from the CONTAINER, never the filesystem; every deliverable
lands in exactly one tri-state bucket; a basename collision refuses.

Workspaces follow the assembly-suite idiom: slots through the real
parser + merge seams; plan/envelope as raw artifacts (the refusal-suite
precedent).
"""

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from engine.assembly.bundle import (
    BUNDLE_NAME,
    compose_bundle,
    declared_deliverables,
)
from engine.assembly.docx_writeback import run_docx_writeback
from engine.contracts import ContractError, validate
from engine.llm import effective_config
from engine.runlog import RunLogger
from engine.structure import merge_parsed, parse_buyer_docx
from engine.version import engine_version
from engine.workspace import PursuitDir

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
AT = "2026-08-29T12:00:00Z"
PROSE = "Founded in 2001, employee-owned, ERP delivery is the practice."


def _log(pursuit):
    log = RunLogger(pursuit.root, pursuit.new_run_id(), pursuit.pursuit_id)
    log.run_start(mode="dry_run", engine_version=engine_version(),
                  config=effective_config(), kb_snapshot="kb@empty")
    return log


def _finish(pursuit, container, *, planned=(), answers=()):
    pursuit.write_artifact("target_slots", container, name="slots.json")
    (pursuit.root / "plan.frozen.json").write_text(json.dumps({
        "pursuit_id": pursuit.pursuit_id, "path": "A_designated",
        "slots_ref": "slots.json", "status": "approved",
        "sections": [{"section_id": "all", "slot_ids": list(planned)}],
    }), encoding="utf-8")
    (pursuit.root / "drafts").mkdir(exist_ok=True)
    (pursuit.root / "drafts" / "draft.json").write_text(json.dumps({
        "plan_sha256": "0" * 64, "revision_n": 1,
        "sections": [{"section_id": "all", "answers": list(answers)}],
    }), encoding="utf-8")
    return pursuit


def _docx_pursuit(tmp_path, pursuit_id="pur_bundle"):
    pursuit = PursuitDir(tmp_path, pursuit_id)
    inbox = pursuit.root / "inbox"
    shutil.copy2(FIXTURES / "qform-twin.docx", inbox / "qform-twin.docx")
    parsed = parse_buyer_docx(inbox / "qform-twin.docx")
    container = {"pursuit_id": pursuit_id, **merge_parsed([parsed])}
    planned = [s["slot_id"] for s in parsed.slots]
    answers = [{"slot_id": "s-t00-r01", "status": "drafted",
                "prose": PROSE}]
    return _finish(pursuit, container, planned=planned, answers=answers)


def _flat_xlsx_pursuit(tmp_path, *, locator_file=True):
    pursuit = PursuitDir(tmp_path, "pur_bundle_x")
    from openpyxl import Workbook
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Response"
    sheet["A1"] = "Approach question"
    source = pursuit.root / "inbox" / "buyer.xlsx"
    workbook.save(source)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    locator = {"sheet": "Response", "cell": "C1"}
    if locator_file:
        locator["file"] = "buyer.xlsx"
    container = {
        "pursuit_id": "pur_bundle_x", "source_mode": "client_provided",
        "parser_version": "test-1", "source_sha256": digest,
        "slot_count": 1,
        "slots": [{"slot_id": "s_prose", "ref_id": "1.1",
                   "source_mode": "client_provided",
                   "response_shape": "prose", "fill_type": "authored",
                   "source_locator": locator}],
    }
    return _finish(pursuit, container, planned=["s_prose"])


def _template_pursuit(tmp_path):
    from engine.structure import parse_default_template
    pursuit = PursuitDir(tmp_path, "pur_bundle_t")
    parsed = parse_default_template(FIXTURES / "template-twin.docx")
    container = {"pursuit_id": "pur_bundle_t", **merge_parsed([parsed])}
    return _finish(pursuit, container)


def test_firm_default_expected_set_is_the_filled_template_alone(tmp_path):
    pursuit = _template_pursuit(tmp_path)
    container = pursuit.read_artifact("slots.json")
    bindings = declared_deliverables(pursuit, container)
    assert [b["lane"] for b in bindings] == ["template_fill"]
    bundle = compose_bundle(pursuit, _log(pursuit), at=AT,
                            composed_by="pat.lee")
    validate("submission_bundle", bundle)
    # ONE deliverable, no submission_render twin (B75§1d: the filled
    # template IS the response document)
    assert [d["lane"] for d in bundle["deliverables"]] == ["template_fill"]
    assert bundle["deliverables"][0]["status"] == "absent"


def test_flat_xlsx_set_is_writeback_plus_render(tmp_path):
    pursuit = _flat_xlsx_pursuit(tmp_path)
    bundle = compose_bundle(pursuit, _log(pursuit), at=AT,
                            composed_by="pat.lee")
    validate("submission_bundle", bundle)
    lanes = [d["lane"] for d in bundle["deliverables"]]
    assert lanes == ["xlsx_writeback", "submission_render"]
    by_lane = {d["lane"]: d for d in bundle["deliverables"]}
    assert by_lane["xlsx_writeback"]["path"] == "exports/writeback/buyer.xlsx"
    assert all(d["status"] == "absent" for d in bundle["deliverables"])


def test_flat_container_without_locator_file_binds_by_digest(tmp_path):
    """The xlsx parser stamps no locator file — the digest is the
    identity (the exact-file rule), so the binding resolves through the
    inbox scan, never a guess."""
    pursuit = _flat_xlsx_pursuit(tmp_path, locator_file=False)
    container = pursuit.read_artifact("slots.json")
    bindings = declared_deliverables(pursuit, container)
    assert bindings[0]["file"] == "buyer.xlsx"
    assert bindings[0]["lane"] == "xlsx_writeback"
    assert bindings[0]["facts_name"] == "exports/writeback-facts.json"


def test_multi_source_set_names_per_file_facts(tmp_path):
    pursuit = PursuitDir(tmp_path, "pur_bundle_m")
    inbox = pursuit.root / "inbox"
    shutil.copy2(FIXTURES / "qform-twin.docx", inbox / "qform-twin.docx")
    parsed_docx = parse_buyer_docx(inbox / "qform-twin.docx")
    from engine.structure import parse_workbook
    shutil.copy2(FIXTURES / "demo-twin.xlsx", inbox / "demo-twin.xlsx")
    parsed_xlsx = parse_workbook(inbox / "demo-twin.xlsx")
    container = {"pursuit_id": "pur_bundle_m",
                 **merge_parsed([parsed_docx, parsed_xlsx])}
    _finish(pursuit, container)
    bindings = declared_deliverables(pursuit, container)
    assert [(b["lane"], b["prefix"], b["facts_name"]) for b in bindings] == [
        ("docx_writeback", "f00-", "exports/docx-writeback-facts-f00.json"),
        ("xlsx_writeback", "f01-", "exports/writeback-facts-f01.json"),
    ]
    bundle = compose_bundle(pursuit, _log(pursuit), at=AT,
                            composed_by="pat.lee")
    validate("submission_bundle", bundle)
    # every expected deliverable RECORDED before any lane has run — the
    # absence the P18 row exists to make loud
    assert [(d["name"], d["status"]) for d in bundle["deliverables"]] == [
        ("qform-twin.docx", "absent"), ("demo-twin.xlsx", "absent"),
        ("response.docx", "absent")]


def test_produced_entries_carry_digest_and_decision_record(tmp_path):
    pursuit = _docx_pursuit(tmp_path)
    run_docx_writeback(pursuit, _log(pursuit), at=AT,
                       confirmed_by="pat.lee")
    bundle = compose_bundle(pursuit, _log(pursuit), at=AT,
                            composed_by="pat.lee")
    validate("submission_bundle", bundle)
    by_lane = {d["lane"]: d for d in bundle["deliverables"]}
    produced = by_lane["docx_writeback"]
    assert produced["status"] == "produced"
    output = pursuit.root / produced["path"]
    assert produced["sha256"] == hashlib.sha256(
        output.read_bytes()).hexdigest()
    assert produced["facts_path"] == "exports/docx-writeback-facts.json"
    assert produced["revision_n"] == 1
    # the render half of the set has not run: recorded, not omitted
    assert by_lane["submission_render"]["status"] == "absent"
    # the artifact line rode the run log
    runs = sorted((pursuit.root / "runs").glob("*/run.jsonl"))
    records = [json.loads(line)
               for line in runs[-1].read_text().splitlines()]
    kinds = [r["artifact"]["kind"] for r in records
             if r.get("record_type") == "artifact"]
    assert kinds == ["submission_bundle"]


def test_facts_without_output_never_reads_produced(tmp_path):
    pursuit = _docx_pursuit(tmp_path)
    run_docx_writeback(pursuit, _log(pursuit), at=AT,
                       confirmed_by="pat.lee")
    (pursuit.root / "exports" / "writeback" / "qform-twin.docx").unlink()
    bundle = compose_bundle(pursuit, _log(pursuit), at=AT,
                            composed_by="pat.lee")
    by_lane = {d["lane"]: d for d in bundle["deliverables"]}
    assert by_lane["docx_writeback"]["status"] == "absent"
    assert "sha256" not in by_lane["docx_writeback"]


def test_door_carried_refusal_is_recorded(tmp_path):
    pursuit = _flat_xlsx_pursuit(tmp_path)
    bundle = compose_bundle(
        pursuit, _log(pursuit), at=AT, composed_by="pat.lee",
        refusals=[{"lane": "xlsx_writeback", "file": "buyer.xlsx",
                   "reason": "no inbox workbook matches source_sha256"}])
    validate("submission_bundle", bundle)
    by_lane = {d["lane"]: d for d in bundle["deliverables"]}
    assert by_lane["xlsx_writeback"]["status"] == "refused"
    assert "source_sha256" in by_lane["xlsx_writeback"]["reason"]


def test_basename_collision_refuses(tmp_path):
    pursuit = PursuitDir(tmp_path, "pur_bundle_c")
    container = {
        "pursuit_id": "pur_bundle_c", "source_mode": "client_provided",
        "parser_version": "test-1", "source_sha256": "a" * 64,
        "slot_count": 0, "slots": [],
        "sources": [
            {"file": "dup.docx", "source_sha256": "b" * 64,
             "parser_version": "test-1"},
            {"file": "dup.docx", "source_sha256": "c" * 64,
             "parser_version": "test-1"},
        ],
    }
    _finish(pursuit, container)
    with pytest.raises(ContractError, match="basename collision"):
        compose_bundle(pursuit, _log(pursuit), at=AT,
                       composed_by="pat.lee")


def test_recompose_overwrites_the_current_state(tmp_path):
    pursuit = _docx_pursuit(tmp_path)
    compose_bundle(pursuit, _log(pursuit), at=AT, composed_by="pat.lee")
    first = pursuit.read_artifact(BUNDLE_NAME)
    assert all(d["status"] == "absent" for d in first["deliverables"])
    run_docx_writeback(pursuit, _log(pursuit), at=AT,
                       confirmed_by="pat.lee")
    compose_bundle(pursuit, _log(pursuit),
                   at="2026-08-29T13:00:00Z", composed_by="pat.lee")
    second = pursuit.read_artifact(BUNDLE_NAME)
    assert second["at"] == "2026-08-29T13:00:00Z"
    by_lane = {d["lane"]: d for d in second["deliverables"]}
    assert by_lane["docx_writeback"]["status"] == "produced"
