"""Resume (N2), third-writer edition: the pre-gate brief is byte-identical
across kill/resume and rerun; the post-gate brief is byte-identical GIVEN
the injected `at` (B22(8)); a mid-gate crash (brief stamped, checkpoint
missing) completes convergently on a same-args call (B22(10))."""

import json

import pytest

from engine.runlog import read_run
from engine.strategy import FROZEN_BRIEF, approve_gate1
from engine.workspace import PursuitDir
from tests.strategy.fixtures.strategies import (
    ACTOR,
    GATE_AT,
    SCRIPT,
    bare_strategy_run,
    run_strategy_package,
)


class Boom(Exception):
    pass


def _exploding_judge(prompt: str) -> str:
    if prompt.startswith("Task: judge."):
        raise Boom("killed between the generate and judge calls")
    return SCRIPT["win_theme_strategist"](prompt)


def test_pregate_rerun_is_byte_identical_with_no_new_calls(tmp_path):
    pursuit, _ = run_strategy_package(tmp_path, gate=None)
    first_bytes = (pursuit.root / "brief.json").read_bytes()
    report, log_path = bare_strategy_run(tmp_path, pursuit)
    assert report.status == "complete"
    assert (pursuit.root / "brief.json").read_bytes() == first_bytes
    rerun = read_run(log_path)
    assert not [r for r in rerun if r["record_type"] == "agent_call"]
    assert [r["record_type"] for r in rerun if r.get("stage") == "win_themes"] \
        == ["stage_start", "artifact", "stage_end"]


def test_crash_mid_stage_resumes_byte_identical(tmp_path):
    reference, _ = run_strategy_package(tmp_path / "ref", gate=None)
    reference_bytes = (reference.root / "brief.json").read_bytes()

    crash_root = tmp_path / "crash"
    with pytest.raises(Boom):
        run_strategy_package(
            crash_root, script={"win_theme_strategist": _exploding_judge},
            gate=None)
    crashed = PursuitDir(crash_root, "pur_pdf")
    assert "win_themes" not in crashed.completed_stages()
    assert "win_themes" not in crashed.read_artifact("brief.json")

    report, _ = bare_strategy_run(crash_root, crashed)
    assert report.status == "complete"
    assert (crashed.root / "brief.json").read_bytes() == reference_bytes


def test_postgate_deterministic_given_at(tmp_path):
    first, _ = run_strategy_package(tmp_path / "a")
    second, _ = run_strategy_package(tmp_path / "b")
    assert ((first.root / "brief.json").read_bytes()
            == (second.root / "brief.json").read_bytes())
    assert ((first.root / FROZEN_BRIEF).read_bytes()
            == (second.root / FROZEN_BRIEF).read_bytes())


def test_midgate_crash_completes_convergently(tmp_path):
    pursuit, _ = run_strategy_package(tmp_path)
    brief_bytes = (pursuit.root / "brief.json").read_bytes()
    frozen_bytes = (pursuit.root / FROZEN_BRIEF).read_bytes()

    # simulate a crash after the brief stamp, before freeze and checkpoint
    (pursuit.root / "checkpoints" / "gate_1.json").unlink()
    (pursuit.root / FROZEN_BRIEF).unlink()

    from engine.runlog import RunLogger
    log = RunLogger(pursuit.root, pursuit.new_run_id(), pursuit.pursuit_id)
    result = approve_gate1(pursuit, log, decision="approved", actor=ACTOR,
                           at=GATE_AT)
    assert result.frozen_path is not None
    assert (pursuit.root / FROZEN_BRIEF).read_bytes() == frozen_bytes
    assert (pursuit.root / "brief.json").read_bytes() == brief_bytes
    payload = json.loads(
        (pursuit.root / "checkpoints" / "gate_1.json").read_text())["payload"]
    assert (payload["decision"], payload["actor"], payload["at"]) == \
        ("approved", ACTOR, GATE_AT)