"""Fresh == resume for planning (B21(7)/N2): a run killed between the
guarded path stage and the plan write resumes to byte-identical
artifacts with zero re-spend and zero re-emitted gap lines."""

import pytest

from engine.kb import KBStore
from engine.llm import FakeCaller, TracedCaller, effective_config
from engine.planning import run_planning
from engine.runlog import RunLogger, read_run
from engine.version import engine_version
from tests.planning.fixtures.plans import (
    FIXTURES,
    planning_extras,
    run_planning_package,
)


@pytest.fixture(scope="module")
def planned(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("plan-resume")
    pursuit, report = run_planning_package(tmp, package_id="gapcase", gate2=None)
    return tmp, pursuit, report


def test_kill_mid_planning_resumes_to_identical_plan(planned):
    tmp, pursuit, _ = planned
    reference = (pursuit.root / "plan.json").read_bytes()

    # Crash window: path_a_map checkpointed, plan not yet written.
    (pursuit.root / "plan.json").unlink()
    pursuit.clear_checkpoint("pursuit_plan")

    store = KBStore(tmp / "kb")
    log = RunLogger(pursuit.root, pursuit.new_run_id(), pursuit.pursuit_id)
    caller = TracedCaller(FakeCaller({}), log)
    cfg = effective_config(extra=planning_extras())
    log.run_start(mode="dry_run", engine_version=engine_version(), config=cfg,
                  kb_snapshot=store.snapshot(),
                  research_mode=cfg["research_mode"])
    report = run_planning(pursuit, caller, log, store,
                          workbook=FIXTURES / "gapcase-twin.xlsx")
    log.run_end(status="awaiting_gate")

    assert report.status == "complete"
    assert (pursuit.root / "plan.json").read_bytes() == reference

    # The resumed run replays from the checkpoint: no searches, no gap
    # lines (totals.gaps_opened must not double-count), no spend.
    records = read_run(log.path)
    kinds = [r["record_type"] for r in records]
    assert "kb_retrieval" not in kinds and "gap" not in kinds
    assert "agent_call" not in kinds
    assert [(r["record_type"], r.get("stage")) for r in records] == [
        ("run_start", None),
        ("stage_start", "pursuit_plan"),
        ("artifact", "pursuit_plan"),
        ("stage_end", "pursuit_plan"),
        ("run_end", None),
    ]
    assert records[-1]["run"]["totals"]["gaps_opened"] == 0
