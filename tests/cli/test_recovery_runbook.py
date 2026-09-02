"""P0-14 (P26a Group C): the recovery runbook's every named repair is a
behaviour the suite exercises — a runbook step with no test is prose,
not a control. The doc's section names are pinned here; the mechanisms
are pinned by the torn-tail, job-lane, and board tests, and the
diagnosis command is exercised end to end below."""

import json
import subprocess
import sys
from pathlib import Path

from engine.llm import effective_config
from engine.runlog import RunLogger
from engine.version import engine_version

REPO = Path(__file__).resolve().parents[2]
RUNBOOK = REPO / "docs" / "pilot" / "runbook.md"

SUBSECTIONS = (
    "with a torn final line", "anywhere EARLIER", "without a footer",
    "jobs journal", "checkpoint", "annotated-draft.json", "brief.json",
    "knowledge base",
)


def test_the_runbook_carries_the_recovery_section_and_every_record_class():
    text = RUNBOOK.read_text(encoding="utf-8")
    assert "## Recovery: torn and corrupt files" in text
    body = text.split("## Recovery: torn and corrupt files", 1)[1]
    for marker in SUBSECTIONS:
        assert marker in body, marker
    assert "Never delete `*.frozen.json`" in body


def _run(tmp_path):
    log = RunLogger(tmp_path, "run_0001", "pur_rb")
    log.run_start(mode="dry_run", engine_version=engine_version(),
                  config=effective_config(), kb_snapshot="kb@empty")
    log.emit("agent_call", stage="intake", agent="a", model="fake-mid-1",
             model_tier="mid", tokens={"input": 10, "output": 5},
             cost_usd=0.0)
    log.run_end(status="completed")
    return log.path


def _check_run(path):
    return subprocess.run(
        [sys.executable, "-m", "engine", "check-run", str(path)],
        capture_output=True, text=True, cwd=REPO)


def test_the_documented_check_names_a_torn_tail_and_a_corrupt_line(tmp_path):
    path = _run(tmp_path)
    clean = _check_run(path)
    assert clean.returncode == 0, clean.stdout + clean.stderr
    data = path.read_bytes()
    path.write_bytes(data + b'{"run_id": "run_0001", "seq": 3, "tor')
    torn = _check_run(path)
    assert torn.returncode != 0
    assert "torn final line" in (torn.stdout + torn.stderr)
    lines = data.split(b"\n")
    lines[1] = lines[1][:15]
    path.write_bytes(b"\n".join(lines))
    corrupt = _check_run(path)
    assert corrupt.returncode != 0
    assert "line 2 is not a JSON record" in (corrupt.stdout + corrupt.stderr)
