"""P32c (A3's zero-spend half): the replay door. A pursuit is run again
from its inbox under FakeCaller into a separate workspace with its own
KB contributions withheld; the verdict is read off the trace — the
exclusion fired, nothing self-excluded was surfaced or opened, every
header says replay, every gate is auto_approved — and the bench that
proves it can fail: a stage sabotaged to ignore `exclude` turns it red.
Hygiene is what this proves; quality is A3's other half."""

import hashlib
import json
from pathlib import Path

import pytest

from engine.cli.main import main
from engine.cli.replay import REPLAYS_DIR, run_replay
from engine.cli.slice import run_slice
from engine.evals.replay import (
    BENCH_PURSUIT,
    DERIVED_ID,
    PLANTED_ID,
    deposit_inbox,
    replay_bench,
)
from engine.runlog import read_run

ARTIFACTS = ("brief.json", "brief.frozen.json", "plan.json",
             "plan.frozen.json", "drafts/draft.json",
             "drafts/annotated-draft.json")


@pytest.fixture(scope="module")
def bench(tmp_path_factory):
    return replay_bench(workdir=tmp_path_factory.mktemp("replay-bench"))


def _records(root) -> list[dict]:
    return [r for run in sorted((Path(root) / "runs").glob("*/run.jsonl"))
            for r in read_run(run)]


def _quiet(*_a, **_k):
    return None


def test_the_replay_completes_under_replay_headers(bench):
    assert bench["status"] == "ok", bench["problems"]
    assert bench["replay_runs"] == 6 and bench["headers_ok"]
    records = _records(bench["replay_root"])
    headers = [r["run"] for r in records if r["record_type"] == "run_start"]
    assert len(headers) == 6
    assert all(h["mode"] == "replay" and h["replay_of"] == BENCH_PURSUIT
               for h in headers)
    assert all(r["record_type"] == "run_end"
               for r in [_records(bench["replay_root"])[-1]])
    for name in ARTIFACTS:
        assert (Path(bench["replay_root"]) / name).exists(), name


def test_every_gate_line_is_auto_approved(bench):
    gates = [r["gate"] for r in _records(bench["replay_root"])
             if r["record_type"] == "gate"]
    assert {g["which"] for g in gates} == {"gate_0_intake", "gate_1_strategy",
                                           "gate_2_plan"}
    assert all(g["decision"] == "auto_approved" and g["auto_approved"] is True
               for g in gates)
    assert bench["gates_auto_approved"] is True


def test_the_self_exclusion_fired_and_held(bench):
    assert bench["self_exclusion"] == sorted([PLANTED_ID, DERIVED_ID])
    assert bench["excluded_lines"] >= 1
    assert bench["surfaced_excluded"] == [] and bench["opened_excluded"] == []
    assert bench["no_excluded_card_opened"] is True
    lines = [r["kb"] for r in _records(bench["replay_root"])
             if r["record_type"] == "kb_retrieval"]
    searches = [kb for kb in lines if kb["step"] == "card_search"]
    assert searches
    assert all(PLANTED_ID in kb["excluded"] and DERIVED_ID in kb["excluded"]
               for kb in searches)
    assert any(kb["cards_opened"] for kb in lines)  # the firm KB still grounds


def test_the_replay_selects_the_evidence_the_pursuit_selected(bench):
    """With only the bench's planted cards withheld, the replay's frozen
    plan names the same sections and the same KB hits the original did
    — the exclusion withheld what the pursuit never had."""
    source = json.loads((Path(bench["workspace"]) / BENCH_PURSUIT
                         / "plan.frozen.json").read_text(encoding="utf-8"))
    replay = json.loads((Path(bench["replay_root"]) / "plan.frozen.json")
                        .read_text(encoding="utf-8"))

    def hits(plan):
        return {s["section_id"]: sorted(h["kb_id"] for h in s.get("kb_hits", []))
                for s in plan["sections"]}

    assert hits(replay) == hits(source)
    assert PLANTED_ID not in json.dumps(replay)


def _without_exclude(real):
    def ignores_exclude(*args, **kwargs):
        kwargs.pop("exclude", None)
        return real(*args, **kwargs)
    return ignores_exclude


def test_a_stage_that_ignores_exclude_at_both_doors_opens_the_card(
        tmp_path, monkeypatch):
    """Research sabotaged at search AND open: the planted card is
    surfaced and opened, and the bench says so twice — the opened count
    and the trajectory verb (the mapper's lines still name the card
    excluded while research opened it)."""
    import engine.research.findings as findings

    monkeypatch.setattr(findings, "card_search",
                        _without_exclude(findings.card_search))
    monkeypatch.setattr(findings, "targeted_open",
                        _without_exclude(findings.targeted_open))
    report = replay_bench(workdir=tmp_path)
    assert report["status"] == "ok", report["problems"]
    assert PLANTED_ID in report["surfaced_excluded"]
    assert PLANTED_ID in report["opened_excluded"]
    assert report["no_excluded_card_opened"] is False
    assert PLANTED_ID in report["trajectory_detail"]


def test_research_that_ignores_exclude_at_search_is_caught_at_the_open_door(
        tmp_path, monkeypatch):
    """Search alone sabotaged: the card surfaces into the research
    result, and research's own `targeted_open(exclude=)` refuses it —
    the second control holds, the bench reports the surfacing."""
    import engine.research.findings as findings

    monkeypatch.setattr(findings, "card_search",
                        _without_exclude(findings.card_search))
    report = replay_bench(workdir=tmp_path)
    assert report["status"] == "ok", report["problems"]
    assert PLANTED_ID in report["surfaced_excluded"]
    assert report["opened_excluded"] == []
    assert report["no_excluded_card_opened"] is True


def test_a_mapper_that_ignores_exclude_surfaces_the_card_but_the_open_door_holds(
        tmp_path, monkeypatch):
    import engine.planning.mapper as mapper

    monkeypatch.setattr(mapper, "card_search",
                        _without_exclude(mapper.card_search))
    report = replay_bench(workdir=tmp_path)
    assert report["status"] == "ok", report["problems"]
    assert PLANTED_ID in report["surfaced_excluded"]
    assert report["opened_excluded"] == []  # targeted_open's own refusal
    plan = json.loads((Path(report["replay_root"]) / "plan.frozen.json")
                      .read_text(encoding="utf-8"))
    assert PLANTED_ID in json.dumps(plan)  # the plan named it; the drafter withheld it


def test_the_source_pursuit_is_read_and_never_written(tmp_path):
    workspace = tmp_path / "ws"
    assert run_slice(workspace, out=_quiet).status == "ok"
    deposit_inbox(workspace)
    source = workspace / BENCH_PURSUIT

    def digest():
        return {str(p.relative_to(source)):
                hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(source.rglob("*")) if p.is_file()}

    before = digest()
    result = run_replay(workspace, BENCH_PURSUIT, out=_quiet)
    assert result.status == "ok", result.problems
    assert result.replay_root == workspace / REPLAYS_DIR / BENCH_PURSUIT
    assert digest() == before
    # the committed KB holds nothing from pur_demo: an honest empty set,
    # nothing to withhold, the headers and gates still say replay
    assert result.self_exclusion == [] and result.excluded_lines == 0
    assert result.hygienic


def test_a_replay_never_resumes_or_overwrites(tmp_path):
    workspace = tmp_path / "ws"
    assert run_slice(workspace, out=_quiet).status == "ok"
    deposit_inbox(workspace)
    first = run_replay(workspace, BENCH_PURSUIT, out=_quiet)
    assert first.status == "ok"
    marker = first.replay_root / "brief.json"
    stamp = marker.read_bytes()
    again = run_replay(workspace, BENCH_PURSUIT, out=_quiet)
    assert again.status == "refused"
    assert any("already exists" in p for p in again.problems)
    assert marker.read_bytes() == stamp
    elsewhere = run_replay(workspace, BENCH_PURSUIT,
                           out_workspace=tmp_path / "second", out=_quiet)
    assert elsewhere.status == "ok"
    assert elsewhere.replay_root == tmp_path / "second" / BENCH_PURSUIT


def test_nothing_to_replay_refuses_typed(tmp_path):
    missing = run_replay(tmp_path, "pur_nothing", out=_quiet)
    assert missing.status == "refused"
    assert any("no inbox/" in p for p in missing.problems)
    (tmp_path / "pur_empty" / "inbox").mkdir(parents=True)
    empty = run_replay(tmp_path, "pur_empty", out=_quiet)
    assert empty.status == "refused"
    assert any("no .xlsx in inbox/" in p for p in empty.problems)
    assert not (tmp_path / "replays" / "pur_empty" / "runs").exists()


def test_cli_entry(tmp_path):
    workspace = tmp_path / "ws"
    assert main(["slice", "--ci", "--workspace", str(workspace)]) == 0
    deposit_inbox(workspace)
    out = tmp_path / "out"
    assert main(["replay", BENCH_PURSUIT, "--workspace", str(workspace),
                 "--out", str(out)]) == 0
    assert (out / BENCH_PURSUIT / "runs").is_dir()
    assert main(["replay", BENCH_PURSUIT, "--workspace", str(workspace),
                 "--out", str(out)]) == 2
    assert main(["replay", "pur_nothing", "--workspace", str(workspace)]) == 2
