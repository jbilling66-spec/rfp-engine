"""P1-17 (P26a Group C): a run log whose FINAL line was torn by a crash
mid-append resumes — the torn bytes are truncated (fsync'd), a named
error record opens the resumed run, seq stays gapless, totals match the
complete records — while a torn line anywhere EARLIER is corruption and
refuses by name. Staged at the boundary: the bytes of a real record cut
mid-way, never a whole-run deletion."""

import json

import pytest

from engine.contracts import ContractError, read_jsonl, torn_tail_offset
from engine.llm import effective_config
from engine.runlog import RunLogger, read_run, read_run_report
from engine.version import engine_version


def _open(tmp_path, run_id="run_0001", **kw):
    log = RunLogger(tmp_path, run_id, "pur_torn", **kw)
    return log


def _start(log):
    log.run_start(mode="dry_run", engine_version=engine_version(),
                  config=effective_config(), kb_snapshot="kb@empty")
    for _ in range(2):  # two calls: the tear takes the SECOND one
        log.emit("agent_call", stage="intake", agent="a", model="fake-mid-1",
                 model_tier="mid", tokens={"input": 10, "output": 5},
                 cost_usd=0.001)


def _tear(path, keep_fraction=0.5):
    data = path.read_bytes()
    lines = data.split(b"\n")
    last = lines[-2] if data.endswith(b"\n") else lines[-1]
    head = data[: len(data) - len(last) - (1 if data.endswith(b"\n") else 0)]
    cut = last[: max(1, int(len(last) * keep_fraction))]
    path.write_bytes(head + cut)
    return len(cut)


def test_torn_final_line_is_reported_by_the_reader(tmp_path):
    log = _open(tmp_path)
    _start(log)
    path = log.path
    torn_bytes = _tear(path)
    records, torn = read_run_report(path)
    assert len(records) == 2 and torn and f"{torn_bytes} bytes" in torn  # run_start + call 1
    assert read_run(path) == records  # the plain read tolerates it
    assert torn_tail_offset(path) == len(path.read_bytes()) - torn_bytes


def test_resume_truncates_the_tail_records_the_repair_and_stays_gapless(
        tmp_path):
    log = _open(tmp_path)
    _start(log)
    path = log.path
    torn_bytes = _tear(path)
    resumed = _open(tmp_path, resume=True)
    records = read_run(path)
    assert path.read_bytes().endswith(b"\n")
    repair = records[-1]
    assert repair["record_type"] == "error"
    assert repair["error"]["code"] == "torn_tail_truncated"
    assert f"{torn_bytes} bytes" in repair["error"]["message"]
    assert repair["error"]["recoverable"] is True
    assert resumed.has_footer is False
    resumed.run_end(status="completed")
    records = read_run(path)
    seqs = [r["seq"] for r in records]
    assert seqs == list(range(len(seqs)))
    assert records[-1]["run"]["totals"]["agent_calls"] == 1
    assert resumed.has_footer is True


def test_a_torn_middle_line_is_corruption_not_a_tail(tmp_path):
    log = _open(tmp_path)
    _start(log)
    log.run_end(status="completed")
    path = log.path
    lines = path.read_bytes().split(b"\n")
    lines[1] = lines[1][:20]  # tear the SECOND record, keep the rest
    path.write_bytes(b"\n".join(lines))
    with pytest.raises(ContractError, match="line 2 is not a JSON record"):
        read_jsonl(path)
    with pytest.raises(ContractError):
        _open(tmp_path, resume=True)


def test_a_clean_log_has_no_repair_line(tmp_path):
    log = _open(tmp_path)
    _start(log)
    n = len(read_run(log.path))
    resumed = _open(tmp_path, resume=True)
    assert len(read_run(log.path)) == n
    assert resumed.has_footer is False
