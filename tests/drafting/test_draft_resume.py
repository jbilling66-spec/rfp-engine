"""Resume discipline (N2/B31): fresh == resumed byte-identically, a
completed section never respends, a fired cost ceiling keeps finished
work, and two fresh chains are byte-identical.
"""

import pytest

from engine.llm.caller import CostCeilingExceeded
from engine.runlog import read_run
from engine.workspace import PursuitDir
from tests.drafting.fixtures.drafts import (
    make_drafter_script,
    run_drafting_package,
    run_drafting_run,
)

DELIVERY = "1-delivery-approach"
SPECIAL = "2-special-requirements"


def _bytes(pursuit):
    return ((pursuit.root / "drafts" / "draft.json").read_bytes(),
            (pursuit.root / "plan.json").read_bytes())


@pytest.fixture(scope="module")
def fresh(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("draft-fresh")
    pursuit, report = run_drafting_package(tmp, script=make_drafter_script())
    assert report.status == "complete"
    return pursuit


def test_two_fresh_chains_are_byte_identical(fresh, tmp_path):
    # v1 harvest: deterministic lanes, two identical chains, same bytes.
    pursuit, report = run_drafting_package(tmp_path,
                                           script=make_drafter_script())
    assert report.status == "complete"
    assert _bytes(pursuit) == _bytes(fresh)


def test_fresh_equals_resume_with_zero_respend(fresh, tmp_path):
    with pytest.raises(RuntimeError, match="killed mid-run"):
        run_drafting_package(tmp_path, script=make_drafter_script(
            fail_on_section="2. Special Requirements"))
    pursuit = PursuitDir(tmp_path, "pur_gapcase")
    # Section 1 completed and checkpointed before the kill.
    ckpt = pursuit.checkpoint_payload("drafting")
    assert list(ckpt["sections"]) == [DELIVERY]
    assert ckpt["complete"] is False

    pursuit, report = run_drafting_run(tmp_path, pursuit,
                                       script=make_drafter_script())
    assert report.status == "complete"
    assert _bytes(pursuit) == _bytes(fresh)  # fresh path == resume path

    resumed = read_run(pursuit.root / "runs" / "run_0006" / "run.jsonl")
    calls = [r for r in resumed if r["record_type"] == "agent_call"]
    assert {c["target"]["section_id"] for c in calls} == {SPECIAL}
    assert len(calls) == 2  # draft + check, nothing for the done section
    opens = [r for r in resumed if r["record_type"] == "kb_retrieval"
             and r["kb"]["step"] == "targeted_open"]
    assert opens == []  # the done section's opens never re-run


def test_ceiling_keeps_finished_sections(fresh, tmp_path):
    # v1 harvest: a fired ceiling keeps finished work; resume completes
    # without respending it. The ceiling is derived from the fresh
    # chain's own deterministic costs: it fires on section 2's draft
    # call, after section 1 checkpointed.
    costs = [r["cost_usd"] for r in read_run(
        fresh.root / "runs" / "run_0005" / "run.jsonl")
        if r["record_type"] == "agent_call"]
    assert len(costs) == 4
    ceiling = costs[0] + costs[1] + costs[2] / 2

    with pytest.raises(CostCeilingExceeded):
        run_drafting_package(tmp_path, script=make_drafter_script(),
                             ceiling=ceiling)
    pursuit = PursuitDir(tmp_path, "pur_gapcase")
    ckpt = pursuit.checkpoint_payload("drafting")
    assert list(ckpt["sections"]) == [DELIVERY]  # finished work kept

    pursuit, report = run_drafting_run(tmp_path, pursuit,
                                       script=make_drafter_script())
    assert report.status == "complete"
    assert _bytes(pursuit) == _bytes(fresh)


def test_completed_stage_reruns_as_pure_replay(fresh, tmp_path):
    pursuit, report = run_drafting_package(tmp_path,
                                           script=make_drafter_script())
    before = _bytes(pursuit)
    pursuit, report = run_drafting_run(tmp_path, pursuit,
                                       script=make_drafter_script())
    assert report.status == "complete"
    assert _bytes(pursuit) == before
    replay = read_run(pursuit.root / "runs" / "run_0006" / "run.jsonl")
    assert not any(r["record_type"] == "agent_call" for r in replay)
    assert not any(r["record_type"] == "kb_retrieval" for r in replay)
