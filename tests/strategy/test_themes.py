"""Win-Theme Strategist stage (P5 acceptance, WP4/G4): 6–8 candidates
generated from brief + research, judge-killed to 2–3, every model-authored
candidate citing real finding sources. Citedness is a code gate proven
non-vacuous with a planted bad cite; killed candidates are retained with
their reasons; refusals spend nothing."""

import pytest

from engine.contracts import validate
from engine.llm.frames import wrap_brief_context, wrap_findings
from engine.runlog import read_run
from engine.workspace import PursuitDir
from tests.intake.fixtures.packages import RAMBLE, run_package
from tests.strategy.fixtures.strategies import (
    _BRIEF_RX,
    _FINDINGS_RX,
    ANCHOR_CITE,
    ANCHOR_MARKER,
    KILL_REASON,
    N_GENERATED,
    bare_strategy_run,
    make_script,
    run_strategy_package,
)


@pytest.fixture(scope="module")
def themed(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("themes")
    return run_strategy_package(tmp, gate=None)


def _candidates(pursuit):
    return pursuit.read_artifact("brief.json")["win_themes"]["candidates"]


# ------------------------------------------------------------- stage output


def test_stage_completes_and_brief_revalidates(themed):
    pursuit, report = themed
    assert report.status == "complete"
    brief = pursuit.read_artifact("brief.json")
    validate("bid_brief", brief)
    assert brief["status"] == "gate1_pending"
    assert "created" not in brief          # Gate 1 stamps time, not the stage
    assert "gate1" not in brief
    assert "approved" not in brief["win_themes"]  # pre-gate: candidates only


def test_generation_window(themed):
    pursuit, _ = themed
    assert len(_candidates(pursuit)) == N_GENERATED


def test_candidates_cite_brief_research(themed):
    pursuit, _ = themed
    brief = pursuit.read_artifact("brief.json")
    sources = {f["source"] for f in brief["buyer"]["research_findings"]}
    for candidate in brief["win_themes"]["candidates"]:
        assert candidate["cites"], candidate["theme"]
        assert set(candidate["cites"]) <= sources


def test_theme_text_carries_research_golden(themed):
    pursuit, _ = themed
    anchored = [c for c in _candidates(pursuit) if ANCHOR_CITE in c["cites"]]
    assert anchored  # the pack's strategy-brief section reached a theme
    assert any(ANCHOR_MARKER in c["theme"] for c in anchored)


def test_judge_kills_to_survivor_window(themed):
    pursuit, _ = themed
    candidates = _candidates(pursuit)
    proposed = [c for c in candidates if c["status"] == "proposed"]
    killed = [c for c in candidates if c["status"] == "killed"]
    assert [candidates.index(c) for c in proposed] == [0, 1]  # KEEP_INDEXES
    assert len(killed) == N_GENERATED - 2
    assert all(c["kill_reason"] == KILL_REASON for c in killed)


def test_killed_candidates_retained(themed):
    pursuit, _ = themed
    killed = [c for c in _candidates(pursuit) if c["status"] == "killed"]
    assert killed  # WP4: the record survives the kill
    for candidate in killed:
        assert candidate["kill_reason"]
        assert candidate["cites"]  # the kill does not strip the citation


# --------------------------------------------------------- clamps and gates


def test_overgeneration_truncated(tmp_path):
    pursuit, report = run_strategy_package(
        tmp_path, script=make_script(n_generate=10), gate=None)
    assert len(_candidates(pursuit)) == 8
    assert any("over-generation truncated" in w for w in report.warnings)


def test_undergeneration_warns(tmp_path):
    pursuit, report = run_strategy_package(
        tmp_path, script=make_script(n_generate=4), gate=None)
    assert len(_candidates(pursuit)) == 4  # kept — the human can add at the gate
    assert any("4 candidates generated" in w for w in report.warnings)


def test_excess_keeps_force_killed(tmp_path):
    pursuit, report = run_strategy_package(
        tmp_path, script=make_script(keep=(1, 2, 3, 4, 5)), gate=None)
    candidates = _candidates(pursuit)
    proposed = [c for c in candidates if c["status"] == "proposed"]
    assert len(proposed) == 3  # the first three keeps stay
    forced = [c for c in candidates if "force-killed" in c.get("kill_reason", "")]
    assert len(forced) == 2
    assert any("force-killed" in w for w in report.warnings)


def test_no_keeps_warns(tmp_path):
    pursuit, report = run_strategy_package(
        tmp_path, script=make_script(keep=()), gate=None)
    assert not [c for c in _candidates(pursuit) if c["status"] == "proposed"]
    assert any("only 0 candidates survive" in w for w in report.warnings)


def test_uncited_candidate_dropped_and_reported(tmp_path):
    planted = "https://example.org/not-in-brief"
    pursuit, report = run_strategy_package(
        tmp_path, script=make_script(plant_bad_cite=True), gate=None)
    brief = pursuit.read_artifact("brief.json")
    # non-vacuous: the planted cite is really absent from the findings
    assert planted not in {f["source"] for f in brief["buyer"]["research_findings"]}
    for candidate in brief["win_themes"]["candidates"]:
        assert planted not in candidate["cites"]
    assert len(brief["win_themes"]["candidates"]) == N_GENERATED - 1
    assert any("unknown source" in w and planted in w for w in report.warnings)
    assert any("no traceable source" in w for w in report.warnings)


# ------------------------------------------------------------- frame drift


def test_frames_match_harness_regexes():
    # single-source tripwire: if a frame's shape changes, the derive-wire
    # scripts and this assertion fail together, never silently apart
    assert _FINDINGS_RX.search(wrap_findings("- (web) src | t: claim"))
    assert _BRIEF_RX.search(wrap_brief_context("Buyer: X"))


# ---------------------------------------------------------------- refusals


def test_refuses_without_brief(tmp_path):
    pursuit = PursuitDir(tmp_path, "pur_empty")
    report, log_path = bare_strategy_run(tmp_path, pursuit)
    assert report.status == "refused"
    records = read_run(log_path)
    errors = [r["error"] for r in records if r["record_type"] == "error"]
    assert [e["code"] for e in errors] == ["missing_brief"]
    assert not [r for r in records if r["record_type"] == "agent_call"]


def test_refuses_without_research_findings(tmp_path):
    pursuit, _ = run_package(tmp_path, "pdf", ramble=RAMBLE)  # intake only
    report, log_path = bare_strategy_run(tmp_path, pursuit)
    assert report.status == "refused"
    records = read_run(log_path)
    errors = [r["error"] for r in records if r["record_type"] == "error"]
    assert [e["code"] for e in errors] == ["missing_research"]
    assert not [r for r in records if r["record_type"] == "agent_call"]