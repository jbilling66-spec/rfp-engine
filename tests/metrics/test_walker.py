"""The cross-pursuit walker (c13) — the read path every metric resolves
through, and the three traps it exists to avoid.
"""

import json
from pathlib import Path

import pytest

from engine.metrics.walker import (is_pursuit_dir, production_only,
                                   read_pursuit, run_headers, walk)

FIXTURE_WS = Path(__file__).resolve().parents[1] / "fixtures" / "pursuits"


def test_walks_the_committed_fixture_pursuit():
    pursuits = walk(FIXTURE_WS)
    assert [p.pursuit_id for p in pursuits] == ["pur_metrics"]
    records = pursuits[0]
    assert len(records.runs) == 15   # 6 + 5 + 4 lines across three runs
    assert len(records.events) == 6
    assert len(records.pings) == 1
    assert records.torn_lines == []


def test_reading_never_creates_a_phantom_pursuit(tmp_path):
    """v1 trap 1: PursuitDir.__init__ mkdirs, so a reader that constructs
    one summons the pursuit it came to look at. The walker must touch
    nothing."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    assert walk(workspace) == []
    assert list(workspace.iterdir()) == []

    missing = tmp_path / "never_existed"
    assert walk(missing) == []
    assert not missing.exists()


def test_non_pursuit_neighbours_are_skipped(tmp_path):
    """kb/ and support/ live beside pursuits in a workspace."""
    workspace = tmp_path / "ws"
    (workspace / "kb" / "cards").mkdir(parents=True)
    (workspace / "support").mkdir(parents=True)
    real = workspace / "pur_real"
    (real / "inbox").mkdir(parents=True)
    assert [p.pursuit_id for p in walk(workspace)] == ["pur_real"]
    assert not is_pursuit_dir(workspace / "kb")


def test_a_torn_final_line_is_skipped_and_recorded(tmp_path):
    """Appends are fsync'd but unlocked across processes, so a resolver
    running beside `engine serve` can catch a half-written last line.
    Skipping it is honest; skipping it SILENTLY would not be."""
    root = tmp_path / "pur_torn"
    (root / "events").mkdir(parents=True)
    (root / "inbox").mkdir()
    good = {"event_id": "ev_1", "pursuit_id": "pur_torn", "kind": "accept",
            "at": "2026-08-01T00:00:00Z", "actor_role": "pursuit_lead"}
    (root / "events" / "events.jsonl").write_text(
        json.dumps(good) + "\n" + '{"event_id": "ev_2", "pur',
        encoding="utf-8")

    records = read_pursuit(root)
    assert len(records.events) == 1
    assert records.torn_lines and "torn final line" in records.torn_lines[0]


def test_corruption_that_is_not_the_last_line_still_raises(tmp_path):
    """Tolerance is exactly one line wide. A broken line in the MIDDLE is
    real corruption, and swallowing it would drop records silently."""
    root = tmp_path / "pur_broken"
    (root / "events").mkdir(parents=True)
    (root / "inbox").mkdir()
    good = {"event_id": "ev_1", "pursuit_id": "pur_broken", "kind": "accept",
            "at": "2026-08-01T00:00:00Z", "actor_role": "pursuit_lead"}
    (root / "events" / "events.jsonl").write_text(
        '{"broken": \n' + json.dumps(good) + "\n", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        read_pursuit(root)


def test_run_headers_index_by_run_id():
    records = walk(FIXTURE_WS)[0].runs
    headers = run_headers(records)
    assert set(headers) == {"run_0001", "run_0002", "run_0003"}
    assert headers["run_0003"]["mode"] == "regression_bench"


def test_production_only_drops_bench_runs():
    """O3: replay, regression_bench and dry_run never enter a production
    series."""
    records = walk(FIXTURE_WS)[0].runs
    production = production_only(records)
    assert {r["run_id"] for r in production} == {"run_0001", "run_0002"}
    assert all(r["run_id"] != "run_0003" for r in production)


def test_a_record_with_no_run_header_is_dropped_not_assumed():
    """An unattributable line cannot be PROVEN production, and counting
    it would let a bench run leak in through a missing header."""
    orphan = [{"run_id": "run_9999", "record_type": "agent_call",
               "cost_usd": 5.0}]
    assert production_only(orphan) == []
