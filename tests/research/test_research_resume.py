"""Resume (N2), second writer edition: a run killed between the
research_internal checkpoint and the external call resumes to a
byte-identical brief.json; an already-complete run reruns and converges —
replace-not-append made both the same code path (B21(7))."""

import pytest

from engine.kb import KBStore
from engine.llm import FakeCaller, TracedCaller, effective_config
from engine.research import run_research
from engine.runlog import RunLogger
from engine.version import engine_version
from engine.workspace import PursuitDir
from tests.research.fixtures.pursuits import SCRIPT, run_research_package


class Boom(Exception):
    pass


def _research_run(tmp_root, pursuit, script=None):
    """A fresh research run over an existing pursuit workspace — the resume
    path (no intake rerun, the KB loaded from disk)."""
    store = KBStore(tmp_root / "kb")
    log = RunLogger(pursuit.root, pursuit.new_run_id(), pursuit.pursuit_id)
    caller = TracedCaller(FakeCaller(script or SCRIPT), log)
    cfg = effective_config()
    log.run_start(mode="dry_run", engine_version=engine_version(), config=cfg,
                  kb_snapshot=store.snapshot(), research_mode=cfg["research_mode"])
    report = run_research(pursuit, caller, log, store,
                          mode=cfg["research_mode"],
                          pack=pursuit.root / "inbox" / "research-pack.md")
    log.run_end(status="completed")
    report.log_path = log.path
    return report


def test_resume_after_internal_checkpoint_is_byte_identical(tmp_path):
    reference, _ = run_research_package(tmp_path / "ref")
    reference_bytes = (reference.root / "brief.json").read_bytes()

    def exploding(prompt: str) -> str:
        raise Boom("killed between research_internal checkpoint and external call")

    crash_root = tmp_path / "crash"
    with pytest.raises(Boom):
        run_research_package(crash_root,
                             script={**SCRIPT, "external_researcher": exploding})
    crashed = PursuitDir(crash_root, "pur_pdf")
    assert (crashed.root / "checkpoints" / "research_internal.json").exists()
    assert "research_findings" not in crashed.read_artifact("brief.json")["buyer"]

    report = _research_run(crash_root, crashed)
    assert report.status == "complete"
    assert (crashed.root / "brief.json").read_bytes() == reference_bytes


def test_rerun_over_completed_research_converges(tmp_path):
    pursuit, _ = run_research_package(tmp_path)
    first_bytes = (pursuit.root / "brief.json").read_bytes()
    report = _research_run(tmp_path, pursuit)
    assert report.status == "complete"
    assert (pursuit.root / "brief.json").read_bytes() == first_bytes


def test_research_refuses_a_gated_brief(tmp_path):
    """P1-12: a brief past Gate 1 is never researched again — the rerun
    refuses before any spend and the brief bytes are untouched."""
    from engine.runlog import read_run
    pursuit, _ = run_research_package(tmp_path)
    brief = pursuit.read_artifact("brief.json")
    brief["status"] = "approved"
    pursuit.write_artifact("bid_brief", brief)
    before = (pursuit.root / "brief.json").read_bytes()
    report = _research_run(tmp_path, pursuit)
    assert report.status == "refused"
    assert (pursuit.root / "brief.json").read_bytes() == before
    records = read_run(report.log_path)
    assert [r["error"]["code"] for r in records
            if r["record_type"] == "error"] == ["brief_frozen"]
    assert not any(r["record_type"] == "agent_call" for r in records)


def test_research_external_skips_on_its_checkpoint(tmp_path):
    """P1-12: the external call is checkpointed — a rerun over completed
    research makes NO model call (either researcher explodes if asked)
    and leaves the brief byte-identical."""
    from engine.runlog import read_run
    pursuit, _ = run_research_package(tmp_path)
    first = (pursuit.root / "brief.json").read_bytes()

    def exploding(prompt: str) -> str:
        raise Boom("no researcher may be called again over a checkpoint")

    report = _research_run(tmp_path, pursuit, script={
        **SCRIPT, "internal_researcher": exploding,
        "external_researcher": exploding})
    assert report.status == "complete"
    assert report.findings  # read back from what the stage wrote
    assert (pursuit.root / "brief.json").read_bytes() == first
    assert not any(r["record_type"] == "agent_call"
                   for r in read_run(report.log_path))
