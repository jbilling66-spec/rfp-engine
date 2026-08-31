"""Planning run-log discipline: every line schema-valid and gapless,
the exact fresh Path-A shape, totals reconciliation, and the run
statuses. Zero agent_call lines is the Path-A promise (B28)."""

import pytest

from engine.contracts import check_runlog_payloads, validate
from engine.runlog import assert_seq_gapless, read_run
from tests.planning.fixtures.plans import run_planning_package


@pytest.fixture(scope="module")
def planned(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("plan-runlog")
    pursuit, report = run_planning_package(tmp, package_id="xlsx", gate2=None)
    return pursuit, report


def _records(pursuit):
    return read_run(pursuit.root / "runs" / "run_0004" / "run.jsonl")


def test_every_line_valid_and_gapless(planned):
    pursuit, _ = planned
    records = _records(pursuit)
    for record in records:
        validate("run_log", record)
        check_runlog_payloads(record)
    assert_seq_gapless(records)


def test_fresh_path_a_shape(planned):
    """Hand-derived: 7 answerable slots -> 7 kb_retrieval lines; the
    structured twin covers no manifest obligation (its sheets ask about
    background/integration/pricing, not delivery obligations) -> 7
    obligation gap lines; zero agent calls anywhere."""
    pursuit, _ = planned
    shape = [(r["record_type"], r.get("stage")) for r in _records(pursuit)]
    assert shape == [
        ("run_start", None),
        ("stage_start", "path_a_map"),
        ("artifact", "path_a_map"),          # slots.json (target_slots)
        *[("kb_retrieval", "path_a_map")] * 7,
        *[("gap", "path_a_map")] * 7,
        ("stage_end", "path_a_map"),
        ("stage_start", "pursuit_plan"),
        ("artifact", "pursuit_plan"),
        ("stage_end", "pursuit_plan"),
        ("run_end", None),
    ]


def test_target_slots_artifact_line(planned):
    pursuit, _ = planned
    artifacts = [r["artifact"] for r in _records(pursuit)
                 if r["record_type"] == "artifact"]
    slots_line = next(a for a in artifacts if a["kind"] == "target_slots")
    assert slots_line["path"].endswith("slots.json")
    assert len(slots_line["sha256"]) == 64
    plan_line = next(a for a in artifacts if a["kind"] == "pursuit_plan")
    assert plan_line["path"].endswith("plan.json")


def test_totals_reconcile(planned):
    pursuit, _ = planned
    records = _records(pursuit)
    totals = records[-1]["run"]["totals"]
    assert totals["agent_calls"] == 0
    assert totals["cost_usd"] == 0
    assert totals["gaps_opened"] == len(
        [r for r in records if r["record_type"] == "gap"]
    )
    assert records[-1]["run"]["status"] == "awaiting_gate"
