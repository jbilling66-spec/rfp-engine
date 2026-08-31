"""The M1 slice, CI flavor (frozen acceptance clause 1): end-to-end over
the demo package with zero spend, byte-deterministic, resumable, with the
liveness guard proven to fire and the live gate proven to refuse without
spend. `make slice` invokes the same runner (pinned against the Makefile
text — the orphaned-surface failure class, B34(14))."""

import json
from pathlib import Path

import pytest

from engine.cli.main import main
from engine.cli.slice import DEFAULT_AT, run_slice, verify_slice
from engine.cli.slice_script import ci_script
from engine.runlog import read_run
from engine.workspace import PursuitDir

ROOT = Path(__file__).resolve().parents[2]

ARTIFACTS = ("brief.json", "brief.frozen.json", "plan.json",
             "plan.frozen.json", "drafts/draft.json",
             "drafts/annotated-draft.json")


@pytest.fixture(scope="module")
def happy(tmp_path_factory):
    workspace = tmp_path_factory.mktemp("slice-happy")
    result = run_slice(workspace, out=lambda *_: None)
    return workspace, result


def _pursuit(workspace):
    return PursuitDir(workspace, "pur_demo")


def test_ci_slice_end_to_end(happy):
    workspace, result = happy
    assert result.status == "ok" and result.problems == []
    assert result.ran_stages == ["intake", "gate_0", "research",
                                 "win_themes+gate_1", "planning+gate_2",
                                 "drafting", "validation"]
    root = _pursuit(workspace).root
    for name in ARTIFACTS:
        assert (root / name).exists(), f"missing {name}"
    assert result.packaging is not None
    assert result.cost_usd > 0  # the synthetic cost meter ran


def test_every_run_is_dry_run_with_a_footer(happy):
    workspace, _ = happy
    run_files = sorted((_pursuit(workspace).root / "runs").glob("*/run.jsonl"))
    assert len(run_files) == 6  # one run per stage group
    for run_file in run_files:
        records = read_run(run_file)
        assert records[0]["run"]["mode"] == "dry_run"
        assert records[-1]["record_type"] == "run_end"


def test_second_invocation_skips_everything(happy):
    # The B22(9) proof at the runner level: with brief.frozen.json present
    # the research block is unreachable — a completed slice re-run runs
    # NOTHING and spends nothing.
    workspace, _ = happy
    runs_before = len(list((_pursuit(workspace).root / "runs").iterdir()))
    again = run_slice(workspace, out=lambda *_: None)
    assert again.status == "ok" and again.ran_stages == []
    assert len(list((_pursuit(workspace).root / "runs").iterdir())) \
        == runs_before


def test_two_fresh_slices_are_byte_identical(happy, tmp_path):
    workspace, _ = happy
    second = run_slice(tmp_path, out=lambda *_: None)
    assert second.status == "ok"
    for name in ARTIFACTS:
        assert (_pursuit(workspace).root / name).read_bytes() \
            == (_pursuit(tmp_path).root / name).read_bytes(), name


def test_killed_slice_resumes_byte_identical(happy, tmp_path):
    workspace, _ = happy
    with pytest.raises(RuntimeError, match="scripted slice death"):
        run_slice(tmp_path, out=lambda *_: None,
                  script=ci_script(fail_at_drafting_section="6. Support Model"))
    root = _pursuit(tmp_path).root
    assert not (root / "drafts" / "annotated-draft.json").exists()
    resumed = run_slice(tmp_path, out=lambda *_: None)
    assert resumed.status == "ok"
    # Only drafting + validation ran on resume — the frozen artifacts
    # gated everything upstream.
    assert resumed.ran_stages == ["drafting", "validation"]
    for name in ARTIFACTS:
        assert (root / name).read_bytes() \
            == (_pursuit(workspace).root / name).read_bytes(), name


def test_orphan_guard_fires_on_missing_artifact(tmp_path):
    result = run_slice(tmp_path, out=lambda *_: None)
    assert result.status == "ok"
    pursuit = _pursuit(tmp_path)
    (pursuit.root / "drafts" / "annotated-draft.json").unlink()
    ok, problems = verify_slice(pursuit)
    assert not ok
    assert any("absent" in p for p in problems)


def test_live_gate_refuses_without_rfp_live_and_spends_nothing(
        tmp_path, monkeypatch):
    monkeypatch.delenv("RFP_LIVE", raising=False)
    result = run_slice(tmp_path, live=True, out=lambda *_: None)
    assert result.status == "refused"
    assert any("RFP_LIVE" in p for p in result.problems)
    assert not (tmp_path / "pur_demo" / "runs").exists()  # zero spend


def test_cli_entry_returns_zero(tmp_path):
    code = main(["slice", "--ci", "--fresh",
                 "--workspace", str(tmp_path / "ws")])
    assert code == 0


def test_make_slice_invokes_the_runner_cli():
    # The liveness pin (B34(24)): if the Makefile ever stops invoking the
    # CLI runner, the surface loses its proof and this fails.
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "-m engine slice --ci" in makefile


def test_dispositions_followed_the_approved_policy(happy):
    # J1's canned policy: every open gap draft_flagged, nothing omitted.
    workspace, _ = happy
    plan = json.loads(
        (_pursuit(workspace).root / "plan.frozen.json").read_text())
    statuses = [g["status"] for s in plan["sections"]
                for g in s.get("gaps", [])]
    assert statuses, "the demo package should produce at least one gap"
    assert set(statuses) <= {"draft_flagged"}
