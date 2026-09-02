"""The MIXED acceptance case (P16/C6, the ROADMAP row's named clause):
narrative sections plus a named tab in a separate file, addressed
together — the core document's embedded structure and the declared
workbook merge into ONE slots container, ONE section list, ONE
map-and-ask pass. Path A stays zero-model, so no chain is needed:
an approved+frozen brief and the fixtures prove it end to end.
"""

import json
from pathlib import Path

import pytest

from engine.kb import KBStore
from engine.llm import FakeCaller, TracedCaller, effective_config
from engine.planning import run_planning
from engine.runlog import RunLogger
from engine.version import engine_version
from engine.workspace import PursuitDir
from tests.helpers import plant_freeze

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _brief(structure="mixed"):
    return {"pursuit_id": "pur_mixed", "buyer": {"name": "Synthetic Buyer"},
            "procurement": {"response_structure": structure},
            "requirements_matrix": [], "status": "approved"}


def _run(tmp_path, *, targets, core_doc, structure="mixed"):
    pursuit = PursuitDir(tmp_path, "pur_mixed")
    pursuit.write_artifact("bid_brief", _brief(structure))
    plant_freeze(pursuit, "bid_brief", _brief(structure), validate=True)
    store = KBStore(tmp_path / "kb")
    log = RunLogger(pursuit.root, pursuit.new_run_id(), pursuit.pursuit_id)
    caller = TracedCaller(FakeCaller({}), log)
    log.run_start(mode="dry_run", engine_version=engine_version(),
                  config=effective_config(), kb_snapshot=store.snapshot())
    report = run_planning(pursuit, caller, log, store,
                          targets=targets, core_doc=core_doc)
    log.run_end(status="completed")
    return pursuit, report


@pytest.fixture(scope="module")
def mixed(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("mixed")
    return _run(tmp, targets=[FIXTURES / "demo-twin.xlsx"],
                core_doc=FIXTURES / "narrative-twin.docx")


def test_mixed_addresses_both_files_together(mixed):
    pursuit, report = mixed
    assert report.status == "complete"
    assert report.path == "A_designated"
    container = json.loads(
        (pursuit.root / "slots.json").read_text(encoding="utf-8"))
    assert [s["file"] for s in container["sources"]] == [
        "demo-twin.xlsx", "narrative-twin.docx"]
    files = {s.get("source_locator", {}).get("file")
             for s in container["slots"]}
    assert files == {"demo-twin.xlsx", "narrative-twin.docx"}


def test_mixed_sections_span_sheets_and_headings(mixed):
    pursuit, _ = mixed
    plan = json.loads((pursuit.root / "plan.json").read_text(encoding="utf-8"))
    titles = [s["title"] for s in plan["sections"]]
    assert any("Technical Approach" in t for t in titles)   # from the core
    assert any("Subcontracting" in t for t in titles)       # from the tab
    assert any(t.startswith("Fill-in table") for t in titles)  # B67-F3


def test_mixed_raises_mapped_gaps_for_the_docx_sections_too(mixed):
    """Gate 2's map-and-ask works for every shape (the acceptance
    clause): the empty KB gaps the core document's prose sections with
    slot-joined gaps, exactly as it does the workbook's."""
    pursuit, _ = mixed
    plan = json.loads((pursuit.root / "plan.json").read_text(encoding="utf-8"))
    docx_section = next(s for s in plan["sections"]
                        if "Technical Approach" in s["title"])
    assert docx_section["gaps"]
    assert docx_section["gaps"][0]["slot_id"] in set(docx_section["slot_ids"])


def test_pdf_core_limitation_is_recorded_never_faked(tmp_path):
    pursuit, report = _run(tmp_path,
                           targets=[FIXTURES / "demo-twin.xlsx"],
                           core_doc=FIXTURES / "pdf-twin.pdf")
    assert report.status == "complete"
    assert any("not scannable offline" in w for w in report.warnings)
    plan = json.loads((pursuit.root / "plan.json").read_text(encoding="utf-8"))
    container = json.loads(
        (pursuit.root / "slots.json").read_text(encoding="utf-8"))
    assert "sources" not in container  # single parsed target, single shape


def test_declared_docx_target_plans_start_to_finish(tmp_path):
    """A pursuit whose ONLY declared target is a buyer Word outline
    reaches a complete plan — the lane v1 never had."""
    pursuit, report = _run(tmp_path,
                           targets=[FIXTURES / "outline-twin.docx"],
                           core_doc=None, structure="designated")
    assert report.status == "complete"
    plan = json.loads((pursuit.root / "plan.json").read_text(encoding="utf-8"))
    titles = [s["title"] for s in plan["sections"]]
    assert "Executive Summary" in titles
    two = next(s for s in plan["sections"]
               if s["title"] == "Implementation Approach")
    assert len(two["slot_ids"]) == 2  # 2 and its child 2.1, one section
