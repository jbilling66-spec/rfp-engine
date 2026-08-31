"""The `serve --handoff` switch (P20/B81): the PIPELINE caller becomes
the handoff seam — assistant and advisor stay FakeCaller — and the flag
alone spends nothing (a handoff call consumes an operator seat, never a
key). Mirrors the --live-assistant proof shape (tests/assistant/
test_serve_flag.py), including the boom-on-unflagged negative."""

import argparse

from fastapi.testclient import TestClient

from engine.cli.serve import register, run_serve


def _parse(argv):
    parser = argparse.ArgumentParser()
    register(parser.add_subparsers(dest="command", required=True))
    return parser.parse_args(argv)


def test_handoff_flags_registered_and_default_off():
    args = _parse(["serve"])
    assert args.handoff is False
    assert args.handoff_timeout == 900.0
    assert _parse(["serve", "--handoff"]).handoff is True


def test_handoff_serve_wires_the_pipeline_seam(tmp_path, monkeypatch):
    """The positive twin first: with the flag, the app reports
    mode=handoff and the pending-calls directory exists eagerly (the
    caller is constructed at serve time, not at first judgment)."""
    captured = {}
    monkeypatch.setattr("uvicorn.run",
                        lambda app, **k: captured.update(app=app))
    workspace = tmp_path / "ws"
    args = _parse(["serve", "--workspace", str(workspace), "--handoff"])
    assert run_serve(args) == 0
    assert (workspace / "pending-calls").is_dir()
    with TestClient(captured["app"]) as client:
        assert client.get("/api/health").json()["mode"] == "handoff"


def test_default_serve_never_constructs_a_handoff_caller(tmp_path,
                                                         monkeypatch):
    """Without the flag, the handoff path is never reached — proven by
    making the constructor explode (the test_serve_flag idiom)."""
    def _boom(*a, **k):
        raise AssertionError("handoff path reached without the flag")

    monkeypatch.setattr("engine.llm.HandoffCaller", _boom)
    monkeypatch.setattr("uvicorn.run", lambda app, **k: None)
    args = _parse(["serve", "--workspace", str(tmp_path / "ws")])
    assert run_serve(args) == 0
