"""RunLogger's two guards (P25 item 3; P2-12, P0-3): a run id is one
path-safe segment, and a NEW run never reopens another run's log —
`resume=True` is the one way to continue a run."""

import pytest

from engine.contracts import ContractError
from engine.runlog import RunLogger, read_run


def _start(log):
    log.run_start(mode="dry_run", engine_version="0.0.0+test",
                  config={}, kb_snapshot="kb@empty")


def test_run_id_must_be_a_plain_segment(tmp_path):
    for bad in ("../x", "run_0001/x", "", "Run_0001", "run 1", "a" * 65):
        with pytest.raises(ContractError, match="plain minted name"):
            RunLogger(tmp_path / "pur_t", bad, "pur_t")
    assert not (tmp_path / "x").exists()
    RunLogger(tmp_path / "pur_t", "run_0001", "pur_t")
    RunLogger(tmp_path / "pur_t", "sas_ab12cd34", "assistant")


def test_new_run_never_reopens_an_existing_log_but_resume_continues(tmp_path):
    log = RunLogger(tmp_path / "pur_t", "run_0001", "pur_t")
    _start(log)
    log.run_end(status="completed")
    with pytest.raises(ContractError, match="already exists"):
        RunLogger(tmp_path / "pur_t", "run_0001", "pur_t")
    again = RunLogger(tmp_path / "pur_t", "run_0001", "pur_t", resume=True)
    records = read_run(again.path)
    assert records[-1]["record_type"] == "run_end"
    assert again._seq == records[-1]["seq"] + 1  # seq continues, no restart
