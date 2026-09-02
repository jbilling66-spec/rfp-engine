"""The xlsx lane goes per-file (P18/C4, B77§2 D1/D7): a second-declared
workbook binds by ITS sources[] digest (the top-level-digest-only scan
retired), its facts land under the fNN name, foreign files' slots never
appear in its record, and the Path-A guard states its true role — an
invariant, not a reachable lane (B77§2 D5).
"""

import hashlib
import json
import shutil
from pathlib import Path

import pytest
from openpyxl import load_workbook

from engine.assembly.bundle import declared_deliverables
from engine.assembly.writeback import preview_writeback, run_writeback
from engine.contracts import ContractError, validate
from engine.llm import effective_config
from engine.runlog import RunLogger
from engine.structure import merge_parsed, parse_buyer_docx, parse_workbook
from engine.version import engine_version
from engine.workspace import PursuitDir
from tests.helpers import plant_freeze

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
AT = "2026-08-29T12:00:00Z"
PROSE = "Cutover completes inside the rehearsal-validated window."


def _log(pursuit):
    log = RunLogger(pursuit.root, pursuit.new_run_id(), pursuit.pursuit_id)
    log.run_start(mode="dry_run", engine_version=engine_version(),
                  config=effective_config(), kb_snapshot="kb@empty")
    return log


@pytest.fixture()
def multi(tmp_path):
    """qform-twin.docx (f00) + demo-twin.xlsx (f01) declared together;
    the envelope drafts one prose slot on EACH file."""
    pursuit = PursuitDir(tmp_path, "pur_wbmulti")
    inbox = pursuit.root / "inbox"
    shutil.copy2(FIXTURES / "qform-twin.docx", inbox / "qform-twin.docx")
    shutil.copy2(FIXTURES / "demo-twin.xlsx", inbox / "demo-twin.xlsx")
    parsed = [parse_buyer_docx(inbox / "qform-twin.docx"),
              parse_workbook(inbox / "demo-twin.xlsx")]
    container = {"pursuit_id": "pur_wbmulti", **merge_parsed(parsed)}
    pursuit.write_artifact("target_slots", container, name="slots.json")
    planned = [s["slot_id"] for s in container["slots"]
               if not s.get("is_header")]
    plant_freeze(pursuit, "pursuit_plan", {
        "pursuit_id": "pur_wbmulti", "path": "A_designated",
        "slots_ref": "slots.json", "status": "approved",
        "sections": [{"section_id": "all", "slot_ids": planned}],
    })
    answers = [
        {"slot_id": "f00-s-t00-r01", "status": "drafted", "prose": PROSE},
        {"slot_id": "f01-slot_01_r002", "status": "drafted",
         "prose": PROSE},
    ]
    (pursuit.root / "drafts").mkdir(exist_ok=True)
    (pursuit.root / "drafts" / "draft.json").write_text(json.dumps({
        "plan_sha256": "0" * 64, "revision_n": 1,
        "sections": [{"section_id": "all", "answers": answers}],
    }), encoding="utf-8")
    container = pursuit.read_artifact("slots.json")
    xlsx_binding = [b for b in declared_deliverables(pursuit, container)
                    if b["lane"] == "xlsx_writeback"][0]
    return pursuit, xlsx_binding


def test_second_declared_workbook_binds_and_fills(multi):
    pursuit, binding = multi
    assert binding["prefix"] == "f01-"
    facts = run_writeback(pursuit, _log(pursuit), at=AT,
                          confirmed_by="pat.lee", binding=binding)
    validate("writeback_facts", facts)
    assert facts["source_file"] == "inbox/demo-twin.xlsx"
    assert facts["output_file"] == "exports/writeback/demo-twin.xlsx"
    output = pursuit.root / facts["output_file"]
    sheet = load_workbook(output)["1. Implementation Methodology"]
    assert sheet["C2"].value == PROSE
    # the inbox original never mutated
    original = pursuit.root / "inbox" / "demo-twin.xlsx"
    assert hashlib.sha256(original.read_bytes()).hexdigest() \
        == binding["source_sha256"]


def test_per_file_facts_land_under_the_fnn_name(multi):
    pursuit, binding = multi
    assert binding["facts_name"] == "exports/writeback-facts-f01.json"
    run_writeback(pursuit, _log(pursuit), at=AT,
                  confirmed_by="pat.lee", binding=binding)
    stored = pursuit.read_artifact("exports/writeback-facts-f01.json")
    validate("writeback_facts", stored)
    # the legacy single-source name was NOT taken — nothing collides
    assert not (pursuit.root / "exports" / "writeback-facts.json").exists()


def test_foreign_file_slots_never_enter_this_record(multi):
    pursuit, binding = multi
    facts = preview_writeback(pursuit, at=AT, binding=binding)
    assert facts["cells"], "the workbook's own slots must be recorded"
    foreign = [c["slot_id"] for c in facts["cells"]
               if not c["slot_id"].startswith("f01-")]
    assert foreign == []  # the docx file's slots belong to ITS record


def test_wrong_digest_still_refuses_per_file(multi):
    pursuit, binding = multi
    (pursuit.root / "inbox" / "demo-twin.xlsx").write_bytes(b"tampered")
    with pytest.raises(ContractError, match="source_sha256"):
        preview_writeback(pursuit, at=AT, binding=binding)


def test_path_guard_states_its_invariant_role(multi):
    """B77§2 D5: the revisit re-RECORDS the refusal — Path B has no
    workbook cells by construction, so the guard names B74§3a instead
    of pointing Path B at a docx export it no longer ships through."""
    pursuit, binding = multi
    plan = json.loads((pursuit.root / "plan.frozen.json").read_text())
    plan["path"] = "B_outline"
    plant_freeze(pursuit, "pursuit_plan", plan)
    with pytest.raises(ContractError, match="B74§3a"):
        preview_writeback(pursuit, at=AT, binding=binding)
