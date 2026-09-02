"""Mutating CLI commands take the server's workspace lock (P25 item 2,
P0-4) and `--fresh` refuses to wipe anything but a workspace under the
pursuits root (P2-21). Each refusal is typed (exit 2) and leaves the
tree byte-identical."""

import argparse
import hashlib
from pathlib import Path

from engine.cli.intake import _cmd_run
from engine.cli.kb import _cmd_kb_purge
from engine.cli.slice import fresh_is_safe, run_slice_cli
from engine.workspace.lock import workspace_lock


def _tree_digest(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.name != "serve.lock":
            h.update(str(p.relative_to(root)).encode())
            h.update(p.read_bytes())
    return h.hexdigest()


def test_intake_run_refuses_while_the_workspace_is_held(tmp_path, capsys):
    ws = tmp_path / "ws"
    (ws / "pur_x").mkdir(parents=True)
    (ws / "pur_x" / "note.txt").write_text("untouched")
    before = _tree_digest(ws)
    args = argparse.Namespace(outputs=str(ws), pursuit="pur_x", doc=[],
                              ramble="", wire=str(tmp_path / "wire.json"))
    with workspace_lock(ws, holder="server"):
        assert _cmd_run(args) == 2
    assert "refused" in capsys.readouterr().err
    assert _tree_digest(ws) == before


def test_slice_refuses_while_the_workspace_is_held(tmp_path, capsys):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "jobs.jsonl").write_text("")
    before = _tree_digest(ws)
    args = argparse.Namespace(workspace=str(ws), fresh=False, live=False,
                              handoff=False, handoff_timeout=1.0,
                              at="2026-08-09T09:00:00")
    with workspace_lock(ws, holder="server"):
        assert run_slice_cli(args) == 2
    assert "refused" in capsys.readouterr().err
    assert _tree_digest(ws) == before


def test_kb_purge_refuses_while_the_workspace_is_held(tmp_path, capsys):
    ws = tmp_path / "pursuits"
    (ws / "pur_x").mkdir(parents=True)
    (ws / "pur_x" / "brief.json").write_text("{}")
    before = _tree_digest(ws)
    args = argparse.Namespace(kb=str(tmp_path / "kb"), client="Synthetic",
                              actor="owner", pursuits=str(ws))
    with workspace_lock(ws, holder="server"):
        assert _cmd_kb_purge(args) == 2
    assert "refused" in capsys.readouterr().err
    assert _tree_digest(ws) == before


def test_fresh_wipes_only_a_marked_workspace_under_the_pursuits_root(
        tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    home_like = tmp_path / "elsewhere"
    home_like.mkdir()
    (home_like / "precious.txt").write_text("keep")
    ok, why = fresh_is_safe(home_like)
    assert not ok and "under" in why
    args = argparse.Namespace(workspace=str(home_like), fresh=True,
                              live=False, handoff=False, handoff_timeout=1.0,
                              at="2026-08-09T09:00:00")
    assert run_slice_cli(args) == 2
    assert (home_like / "precious.txt").read_text() == "keep"
    assert "refused" in capsys.readouterr().err
    root = tmp_path / "pursuits"
    assert not fresh_is_safe(root)[0]  # never the root itself
    unmarked = root / "random"
    unmarked.mkdir(parents=True)
    (unmarked / "x.txt").write_text("x")
    assert not fresh_is_safe(unmarked)[0]
    marked = root / "slice-ci"
    (marked / "pur_demo").mkdir(parents=True)
    assert fresh_is_safe(marked)[0]
    assert fresh_is_safe(root / "does-not-exist-yet")[0]
