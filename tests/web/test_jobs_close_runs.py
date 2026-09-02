"""P2-20 (P26a Group C): a job that dies — an exception in its target, or
a server restart with the job mid-run — leaves no footerless run: the
job lane closes the pursuit's open run with a `failed` footer and names
the run on the journal line, and the runs read model reports
`in_flight` only while a job actually holds the pursuit. P1-17's rider:
a torn journal tail is tolerated at rehydrate, not fatal."""

import json

from engine.llm import effective_config
from engine.runlog import RunLogger, read_run
from engine.version import engine_version
from engine.web.jobs import JobRunner
from engine.workspace import PursuitDir
from tests.web.conftest import FIXED_AT


def _open_run(ws, pursuit_id):
    pursuit = PursuitDir(ws, pursuit_id)
    log = RunLogger(pursuit.root, pursuit.new_run_id(), pursuit_id)
    log.run_start(mode="dry_run", engine_version=engine_version(),
                  config=effective_config(), kb_snapshot="kb@empty")
    return pursuit, log


def _wait(runner, job_id, timeout=30.0):
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = runner.get(job_id) if hasattr(runner, "get") else runner._jobs[job_id]
        if job["state"] not in ("queued", "running"):
            return job
        time.sleep(0.05)
    raise TimeoutError(job_id)


def test_a_crashing_job_closes_its_run_with_a_failed_footer(tmp_path):
    ws = tmp_path / "ws"
    runner = JobRunner(ws)
    pursuit, log = _open_run(ws, "pur_crash")
    run_id = log.run_id

    def target(job):
        raise RuntimeError("boom after run_start")

    job = runner.submit(kind="advance", pursuit_id="pur_crash", by="t",
                        at=FIXED_AT, target=target)
    done = _wait(runner, job["id"])
    assert done["state"] == "error"
    records = read_run(pursuit.root / "runs" / run_id / "run.jsonl")
    assert records[-1]["record_type"] == "run_end"
    assert records[-1]["run"]["status"] == "failed"
    journal = [json.loads(l) for l in runner.journal_path.read_text().splitlines()]
    assert journal[-1]["id"] == job["id"] and journal[-1]["run_id"] == run_id


def test_a_job_that_closed_its_own_run_is_not_double_closed(tmp_path):
    ws = tmp_path / "ws"
    runner = JobRunner(ws)
    pursuit, log = _open_run(ws, "pur_clean")

    def target(job):
        log.run_end(status="completed")
        raise RuntimeError("after a clean close")

    job = runner.submit(kind="advance", pursuit_id="pur_clean", by="t",
                        at=FIXED_AT, target=target)
    _wait(runner, job["id"])
    records = read_run(pursuit.root / "runs" / log.run_id / "run.jsonl")
    footers = [r for r in records if r["record_type"] == "run_end"]
    assert len(footers) == 1 and footers[0]["run"]["status"] == "completed"


def test_rehydrate_closes_orphaned_runs_and_tolerates_a_torn_journal_tail(
        tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    pursuit, log = _open_run(ws, "pur_orphan")
    journal = ws / "jobs.jsonl"
    journal.write_text(json.dumps({
        "id": "job-0001", "kind": "advance", "pursuit": "pur_orphan",
        "by": "t", "state": "running", "message": "running",
        "at": FIXED_AT}, sort_keys=True) + "\n" + '{"id": "job-0002", "ki')
    runner = JobRunner(ws)
    assert runner.journal_torn is not None
    assert runner._jobs["job-0001"]["state"] == "orphaned"
    assert runner._jobs["job-0001"]["run_id"] == log.run_id
    records = read_run(pursuit.root / "runs" / log.run_id / "run.jsonl")
    assert records[-1]["run"]["status"] == "failed"
