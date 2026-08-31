"""The `serve --live-assistant` switch (P14/C9): the assistant lane is
the ONLY lane it makes live, and the flag alone still spends nothing —
LiveCaller's own construction refuses without RFP_LIVE=1 (B30(e))."""

import argparse

import pytest

from engine.cli.serve import register, run_serve
from engine.llm.live import LiveCallError


def _parse(argv):
    parser = argparse.ArgumentParser()
    register(parser.add_subparsers(dest="command", required=True))
    return parser.parse_args(argv)


def test_flag_is_registered_and_defaults_off():
    assert _parse(["serve"]).live_assistant is False
    assert _parse(["serve", "--live-assistant"]).live_assistant is True


def test_host_is_still_not_an_argument():
    """B37/D1: 127.0.0.1 only until A5's reverse proxy — the new flag
    must not have quietly opened a host knob."""
    with pytest.raises(SystemExit):
        _parse(["serve", "--host", "0.0.0.0"])


def test_live_assistant_refuses_without_rfp_live(tmp_path, monkeypatch):
    """The flag alone spends nothing: construction refuses BEFORE the
    server starts, so no uvicorn.run is ever reached."""
    monkeypatch.delenv("RFP_LIVE", raising=False)
    args = _parse(["serve", "--workspace", str(tmp_path / "ws"),
                   "--live-assistant"])
    with pytest.raises(LiveCallError, match="RFP_LIVE=1"):
        run_serve(args)


def test_default_serve_never_touches_the_live_caller(tmp_path,
                                                     monkeypatch):
    """Without the flag, nothing in the live module is reached — proven
    by making its import explode."""
    started = {}

    def _boom(*a, **k):
        raise AssertionError("live path reached without the flag")

    monkeypatch.setattr("engine.llm.live.LiveCaller", _boom)
    monkeypatch.setattr("uvicorn.run",
                        lambda app, **k: started.update(k) or None)
    args = _parse(["serve", "--workspace", str(tmp_path / "ws")])
    assert run_serve(args) == 0
    assert started["host"] == "127.0.0.1"
