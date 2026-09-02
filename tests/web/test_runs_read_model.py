"""P2-20 / P1-17 at the runs door: a footerless run reads `in_flight`
only while a job holds the pursuit and `unclosed` otherwise; a torn
final line is reported on the row (`torn_tail`), never hidden; and the
rows come in numeric run order."""

from engine.llm import effective_config
from engine.runlog import RunLogger
from engine.version import engine_version
from engine.workspace import PursuitDir
from tests.web.conftest import sign_in


def _open_run(ws, pid):
    pursuit = PursuitDir(ws, pid)
    log = RunLogger(pursuit.root, pursuit.new_run_id(), pid)
    log.run_start(mode="dry_run", engine_version=engine_version(),
                  config=effective_config(), kb_snapshot="kb@empty")
    return pursuit, log


def test_unclosed_and_torn_tail_are_named(offline_app, tmp_path):
    client = offline_app
    sign_in(client)
    client.post("/api/pursuits", json={"pursuit_id": "pur_runs"})
    ws = tmp_path / "ws"
    _, closed = _open_run(ws, "pur_runs")
    closed.run_end(status="completed")
    _, open_run = _open_run(ws, "pur_runs")
    torn = open_run.path
    data = torn.read_bytes()
    torn.write_bytes(data + b'{"run_id": "run_0002", "seq": 9, "to')
    rows = client.get("/api/pursuits/pur_runs/runs").json()
    assert [r["run_id"] for r in rows] == ["run_0001", "run_0002"]
    assert rows[0]["status"] == "completed" and "torn_tail" not in rows[0]
    assert rows[1]["status"] == "unclosed", "no job holds the pursuit"
    assert "torn final line" in rows[1]["torn_tail"]
