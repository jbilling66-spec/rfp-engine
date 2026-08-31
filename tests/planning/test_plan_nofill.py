"""The no-fill edge twin (EC-3) plans correctly, and a truly slotless
workbook refuses loudly — the two halves of the named regression."""

import pytest
from openpyxl import Workbook

from engine.runlog import read_run
from tests.planning.fixtures.plans import run_planning_package


@pytest.fixture(scope="module")
def planned(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("plan-nofill")
    pursuit, report = run_planning_package(tmp, package_id="nofill", gate2=None)
    return pursuit, report


def test_nofill_parses_four_slots_into_one_section(planned):
    pursuit, report = planned
    assert report.status == "complete"
    plan = pursuit.read_artifact("plan.json")
    assert len(plan["sections"]) == 1
    section = plan["sections"][0]
    assert section["section_id"] == "scope-of-services"
    assert len(section["slot_ids"]) == 4
    # The two-part refs joined the brief matrix (the C5 derive branch).
    assert section["requirement_refs"] == ["1.1", "1.2", "2.1", "2.2"]
    # On-corpus questions ground; no gaps on this twin.
    assert section["kb_hits"] and "gaps" not in section
    assert plan["coverage_summary"]["total_requirements"] == 4
    assert plan["coverage_summary"]["covered"] == 4


def test_truly_slotless_workbook_refuses_empty_parse(planned, tmp_path):
    """Non-vacuous refusal: a real workbook that parses to zero slots
    must refuse loudly (error code empty_parse), never write a zero-slot
    plan. Uses the nofill pursuit's approved brief with a furniture-only
    workbook."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Cover"
    ws["A1"] = "Thank you for the opportunity to respond."
    slotless = tmp_path / "slotless.xlsx"
    wb.save(slotless)

    tmp = tmp_path / "ws"
    pursuit, report = run_planning_package(
        tmp, package_id="nofill", workbook=slotless, gate2=None
    )
    assert report.status == "refused"
    assert not (pursuit.root / "plan.json").exists()
    records = read_run(pursuit.root / "runs" / "run_0004" / "run.jsonl")
    errors = [r["error"]["code"] for r in records if r["record_type"] == "error"]
    assert errors == ["empty_parse"]
    assert not [r for r in records if r["record_type"] == "agent_call"]
