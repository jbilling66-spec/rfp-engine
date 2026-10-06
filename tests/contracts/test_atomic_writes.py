"""engine/contracts/atomic.py — the one atomic-write primitive (P26a
Group B, P0-6). A crash in the middle of a rewrite leaves the OLD bytes
intact and no temp file behind; appends are fsync'd per line; the
record sites the register named (the org store, the run config, the
jobs journal) now route through it; and llm/handoff.py's documented
twin stays equal on its load-bearing lines."""

import inspect
import json
import os

import pytest

from engine.contracts import (
    ContractError,
    append_fsync,
    write_bytes_atomic,
    write_json_atomic,
    write_text_atomic,
)
from engine.contracts import atomic as atomic_mod
from engine.llm import handoff
from engine.workspace import PursuitDir
from engine.workspace.orgs import create_org, list_orgs


def _crash_on_replace(monkeypatch):
    def boom(src, dst):
        raise OSError("simulated crash between fsync and replace")
    monkeypatch.setattr(atomic_mod.os, "replace", boom)


def test_a_crashed_rewrite_leaves_the_old_bytes_and_no_temp(tmp_path,
                                                            monkeypatch):
    target = tmp_path / "record.json"
    write_json_atomic(target, {"v": 1})
    before = target.read_bytes()
    _crash_on_replace(monkeypatch)
    with pytest.raises(OSError, match="simulated crash"):
        write_json_atomic(target, {"v": 2})
    assert target.read_bytes() == before
    assert [p.name for p in tmp_path.iterdir()] == ["record.json"], \
        "the temp file is unlinked on the way out"


def test_bytes_text_and_json_shapes(tmp_path):
    write_bytes_atomic(tmp_path / "b.bin", b"\x00\xff")
    assert (tmp_path / "b.bin").read_bytes() == b"\x00\xff"
    write_text_atomic(tmp_path / "t.txt", "café\n")
    assert (tmp_path / "t.txt").read_text(encoding="utf-8") == "café\n"
    write_json_atomic(tmp_path / "j.json", {"b": 1, "a": [2]})
    assert (tmp_path / "j.json").read_text() == \
        json.dumps({"b": 1, "a": [2]}, indent=2, sort_keys=True) + "\n"
    write_json_atomic(tmp_path / "j1.json", {"a": 1}, indent=1)
    assert (tmp_path / "j1.json").read_text() == '{\n "a": 1\n}\n'


def test_append_fsync_appends_one_line_and_syncs(tmp_path, monkeypatch):
    synced = []
    real = os.fsync
    monkeypatch.setattr(atomic_mod.os, "fsync",
                        lambda fd: (synced.append(fd), real(fd)))
    path = tmp_path / "log.jsonl"
    append_fsync(path, '{"a": 1}')
    append_fsync(path, '{"a": 2}\n')
    assert path.read_text().splitlines() == ['{"a": 1}', '{"a": 2}']
    assert len(synced) == 2


def test_org_store_survives_a_crashed_rewrite(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    ws.mkdir()
    org = create_org(ws, "Synthetic Org", created_by="t",
                     at="2026-09-02T10:00:00")
    path = ws / "orgs" / org["org_id"] / "org.json"
    assert path.is_file()
    before = path.read_bytes()
    _crash_on_replace(monkeypatch)
    from engine.workspace.orgs import _write_org
    with pytest.raises(OSError):
        _write_org(ws, {**org, "known_as": ["Renamed"]})
    assert path.read_bytes() == before
    assert list_orgs(ws)[0]["known_as"] == ["Synthetic Org"]


def test_jobs_journal_lines_are_fsynced(tmp_path, monkeypatch):
    from engine.web.jobs import JobRunner
    synced = []
    real = os.fsync
    monkeypatch.setattr(atomic_mod.os, "fsync",
                        lambda fd: (synced.append(fd), real(fd)))
    runner = JobRunner(tmp_path / "ws")
    runner._journal({"id": "job-1", "kind": "advance", "pursuit": "pur_x",
                     "by": "t", "state": "queued", "message": "m",
                     "at": "2026-09-02T10:00:00"})
    assert synced, "the journal append fsyncs"
    assert json.loads(runner.journal_path.read_text().splitlines()[-1])[
        "id"] == "job-1"


def test_pursuit_write_bytes_is_atomic_and_rooted(tmp_path, monkeypatch):
    pursuit = PursuitDir(tmp_path, "pur_b")
    path = pursuit.write_bytes("inbox/pack.md", b"# pack\n")
    assert path.read_bytes() == b"# pack\n"
    with pytest.raises(ContractError):
        pursuit.write_bytes("../escape.bin", b"x")
    with pytest.raises(ContractError):
        pursuit.write_bytes("brief.frozen.json", b"{}")
    _crash_on_replace(monkeypatch)
    with pytest.raises(OSError):
        pursuit.write_bytes("inbox/pack.md", b"changed")
    assert path.read_bytes() == b"# pack\n"


def test_the_handoff_twin_keeps_the_load_bearing_lines():
    """llm keeps its own copy (B81 D2); this pins the copy to the
    primitive's mechanics — mkstemp beside the target, fsync, os.replace,
    unlink on failure — so the two cannot drift apart silently."""
    twin = inspect.getsource(handoff._atomic_write_json)
    canon = inspect.getsource(atomic_mod.write_bytes_atomic)
    for line in ("tempfile.mkstemp(dir=path.parent, prefix=f\".{path.name}.\")",
                 "os.fsync(f.fileno())", "os.replace(tmp, path)",
                 "Path(tmp).unlink(missing_ok=True)"):
        assert line in twin and line in canon, line


# -- P29b b1 (P1-51/P3-20): the one tail rule ---------------------------------


def test_a_complete_final_record_without_its_newline_gets_one_first(
        tmp_path, monkeypatch):
    """P3-20: a crash that persisted the whole object but dropped the
    final byte parses cleanly, so no reader calls it torn — the appender
    writes the newline before its own line, in the same handle (one
    fsync), and reports the repair by name."""
    synced = []
    real = os.fsync
    monkeypatch.setattr(atomic_mod.os, "fsync",
                        lambda fd: (synced.append(fd), real(fd)))
    path = tmp_path / "log.jsonl"
    path.write_bytes(b'{"a": 1}\n{"a": 2}')  # the final newline lost
    repaired = append_fsync(path, '{"a": 3}')
    assert repaired is not None and repaired[0] == "tail_newline_repaired"
    assert path.read_text().splitlines() == ['{"a": 1}', '{"a": 2}',
                                             '{"a": 3}']
    assert len(synced) == 1


def test_a_torn_final_line_refuses_the_append_unless_repair_is_asked(
        tmp_path, monkeypatch):
    """P1-51: `append_fsync` never concatenates onto a fragment — that
    fused line is the corruption the next reader refuses. Without
    `repair_torn` the append raises by name; with it, the fragment is
    truncated (fsync'd) before the line lands and the bytes dropped are
    reported."""
    synced = []
    real = os.fsync
    monkeypatch.setattr(atomic_mod.os, "fsync",
                        lambda fd: (synced.append(fd), real(fd)))
    path = tmp_path / "log.jsonl"
    path.write_bytes(b'{"a": 1}\n{"a": 2, "ki')
    with pytest.raises(ContractError, match="torn final line"):
        append_fsync(path, '{"a": 3}')
    assert path.read_bytes() == b'{"a": 1}\n{"a": 2, "ki'  # untouched
    repaired = append_fsync(path, '{"a": 3}', repair_torn=True)
    assert repaired is not None and repaired[0] == "torn_tail_truncated"
    assert "12 bytes" in repaired[1]
    assert path.read_text().splitlines() == ['{"a": 1}', '{"a": 3}']
    assert len(synced) == 2  # the truncate and the append


def test_a_clean_tail_reports_no_repair(tmp_path):
    path = tmp_path / "log.jsonl"
    assert append_fsync(path, '{"a": 1}') is None  # a new file
    assert append_fsync(path, '{"a": 2}') is None  # a clean tail
    assert path.read_text() == '{"a": 1}\n{"a": 2}\n'
