"""Manifest items appear as plan obligations (the B16 consumer) — read
from the LIVE manifest so the owner's mid-phase row edits are a suite no-op:
a row he adds that nothing covers lands gapped, which is correct
behavior, not a failure."""

import pytest

from engine.kb.manifest import load_manifest
from engine.planning.plan import MANIFEST_DEFAULT
from engine.runlog import read_run
from tests.planning.fixtures.plans import run_planning_package


@pytest.fixture(scope="module")
def planned(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("plan-obligations")
    pursuit, report = run_planning_package(tmp, package_id="nofill", gate2=None)
    return pursuit, report


def test_plan_obligation_ids_equal_live_manifest(planned):
    pursuit, _ = planned
    manifest = load_manifest(MANIFEST_DEFAULT)
    rows = pursuit.read_artifact("plan.json")["obligations"]
    assert [r["id"] for r in rows] == manifest.obligation_ids()  # order too
    for row in rows:
        assert row["status"] in ("covered", "gapped")
        if row["status"] == "covered":
            assert row["section_ids"]  # a cover names its section
        else:
            assert "section_ids" not in row


def test_known_rows_disposition_on_the_nofill_twin(planned):
    """Guarded spot checks (only when the live manifest still carries the
    row): the nofill twin's four questions map to four obligations, one
    via the OCM acronym expansion; the rest are honestly gapped."""
    pursuit, _ = planned
    status = {r["id"]: r["status"]
              for r in pursuit.read_artifact("plan.json")["obligations"]}
    for oid, expected in [("pm-approach", "covered"),
                          ("staffing-plan", "covered"),
                          ("testing-methodology", "covered"),
                          ("training-ocm", "covered"),  # via ACRONYMS
                          ("data-migration", "gapped"),
                          ("support-hypercare", "gapped")]:
        if oid in status:
            assert status[oid] == expected, oid


def test_gapped_obligation_emits_runlog_gap(planned):
    pursuit, _ = planned
    rows = pursuit.read_artifact("plan.json")["obligations"]
    gapped = [r for r in rows if r["status"] == "gapped"]
    assert gapped  # non-vacuous on this twin
    records = read_run(pursuit.root / "runs" / "run_0004" / "run.jsonl")
    gap_lines = [r["gap"] for r in records if r["record_type"] == "gap"]
    for row in gapped:
        matching = [g for g in gap_lines
                    if f"core-content manifest / {row['id']}" in
                    g["question_to_human"]]
        assert len(matching) == 1, row["id"]
        assert matching[0]["reason"] == "needs_sme"
        assert matching[0]["resolution"] == "unresolved"
