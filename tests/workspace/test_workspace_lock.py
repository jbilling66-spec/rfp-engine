"""The cross-process workspace lock (P25 item 2, P0-4): one writer per
workspace across PROCESSES — a second holder in the same process and in
a subprocess both refuse loudly, naming the holder; release restores."""

import subprocess
import sys
import textwrap

import pytest

from engine.workspace.lock import WorkspaceLocked, workspace_lock


def test_second_holder_in_process_refuses_and_release_restores(tmp_path):
    ws = tmp_path / "ws"
    lock = workspace_lock(ws, holder="first")
    assert lock.held and (ws / "serve.lock").read_text().startswith("first")
    with pytest.raises(WorkspaceLocked, match="first"):
        workspace_lock(ws, holder="second")
    lock.release()
    assert not lock.held
    with workspace_lock(ws, holder="third") as again:
        assert again.held
    assert not again.held


def test_lock_held_by_another_process_refuses(tmp_path):
    ws = tmp_path / "ws"
    child = subprocess.Popen(
        [sys.executable, "-c", textwrap.dedent(f"""
            import sys, time
            from engine.workspace.lock import workspace_lock
            lock = workspace_lock({str(ws)!r}, holder="child")
            print("held", flush=True)
            sys.stdin.readline()  # hold until the parent says so
            lock.release()
            print("released", flush=True)
        """)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == "held"
        with pytest.raises(WorkspaceLocked, match="child"):
            workspace_lock(ws, holder="parent")
        child.stdin.write("go\n")
        child.stdin.flush()
        assert child.stdout.readline().strip() == "released"
        child.wait(timeout=30)
        with workspace_lock(ws, holder="parent") as lock:
            assert lock.held
    finally:
        if child.poll() is None:
            child.kill()
