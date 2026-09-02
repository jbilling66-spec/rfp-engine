"""Run-logger contract: every line valid, seq gapless, totals reconcile,
foreign payloads refused, resume continues the same run (P0 acceptance)."""

import json

import pytest

from engine.contracts import ContractError
from engine.runlog import (
    RunLogger,
    assert_seq_gapless,
    config_digest,
    digest,
    read_run,
)


@pytest.fixture
def logger(tmp_path):
    return RunLogger(tmp_path / "pur_demo", run_id="run_0001", pursuit_id="pur_demo")


CONFIG = {"research_mode": "airgapped", "effort_allocation": "uniform"}


def _small_run(log: RunLogger) -> None:
    log.run_start(mode="dry_run", engine_version="v2-dev", config=CONFIG,
                  kb_snapshot="kb@test")
    log.emit("stage_start", stage="intake")
    log.emit("agent_call", stage="intake", agent="intake_analyst",
             model="fake-frontier-1", model_tier="frontier",
             tokens={"input": 1000, "output": 200}, cost_usd=0.012)
    log.emit("agent_call", stage="drafting", agent="section_drafter",
             model="fake-mid-1", model_tier="mid",
             tokens={"input": 3000, "output": 900}, cost_usd=0.031)
    log.emit("stage_end", stage="intake")
    log.run_end(status="completed")


def test_every_line_validates_and_seq_is_gapless(logger):
    _small_run(logger)
    records = read_run(logger.path)
    assert_seq_gapless(records)
    assert [r["record_type"] for r in records] == [
        "run_start", "stage_start", "agent_call", "agent_call", "stage_end", "run_end",
    ]


def test_totals_reconcile_against_summed_agent_calls(logger):
    _small_run(logger)
    records = read_run(logger.path)
    totals = records[-1]["run"]["totals"]
    calls = [r for r in records if r["record_type"] == "agent_call"]
    assert totals["agent_calls"] == len(calls)
    assert totals["cost_usd"] == pytest.approx(sum(c["cost_usd"] for c in calls))
    assert totals["input_tokens"] == sum(c["tokens"]["input"] for c in calls)
    assert totals["output_tokens"] == sum(c["tokens"]["output"] for c in calls)


def test_invalid_record_never_lands(logger):
    with pytest.raises(ContractError):
        logger.emit("agent_call", agent="drafter")  # missing model (B10)
    with pytest.raises(ContractError):
        logger.emit("agent_call", agent="drafter", model="fake-mid-1",
                    gate={"decision": "approved"})  # foreign payload
    with pytest.raises(ContractError):
        logger.emit("nonsense_type")
    assert not logger.path.exists() or read_run(logger.path) == []


def test_resume_continues_seq_and_totals(tmp_path):
    pursuit = tmp_path / "pur_demo"
    first = RunLogger(pursuit, run_id="run_0001", pursuit_id="pur_demo")
    first.run_start(mode="dry_run", engine_version="v2-dev", config=CONFIG,
                    kb_snapshot="kb@test")
    first.emit("agent_call", agent="intake_analyst", model="fake-frontier-1",
               tokens={"input": 10, "output": 5}, cost_usd=0.001)
    # process dies here; a new logger reopens the same run
    resumed = RunLogger(pursuit, run_id="run_0001", pursuit_id="pur_demo",
                        resume=True)
    resumed.emit("agent_call", agent="section_drafter", model="fake-mid-1",
                 tokens={"input": 20, "output": 8}, cost_usd=0.002)
    resumed.run_end(status="completed")
    records = read_run(resumed.path)
    assert_seq_gapless(records)
    totals = records[-1]["run"]["totals"]
    assert totals["agent_calls"] == 2
    assert totals["cost_usd"] == pytest.approx(0.003)


def test_config_digest_changes_when_config_changes():
    base = config_digest(CONFIG)
    assert base == config_digest(dict(CONFIG))  # order/copy insensitive
    assert base != config_digest({**CONFIG, "research_mode": "full_web"})


def test_digest_hides_text():
    d = digest("Northwind Regional Health confidential prose")
    assert d.startswith("sha256:")
    assert "Northwind" not in d


def test_spec_sample_run_still_validates_after_errata():
    """The spec's own worked example must pass the amended schema + payload
    discipline — the errata tightened the contract, not changed its meaning."""
    from engine.contracts import check_runlog_payloads, validate

    sample = (
        __import__("pathlib").Path(__file__).resolve().parents[2]
        / "spec" / "observability" / "sample-run.jsonl"
    )
    lines = [json.loads(l) for l in sample.read_text().splitlines() if l.strip()]
    assert len(lines) >= 7
    for record in lines:
        validate("run_log", record)
        check_runlog_payloads(record)
