"""The one spend path (P26a Group A — P1-16's boundary half, P0-1).

`import anthropic` lives in engine/llm/live.py and nowhere else in
engine/ — a second spend path added anywhere is caught here, not by the
RFP_LIVE guard it might forget. And the client the live path builds
carries the explicit timeout and NO SDK-side retries, pinned against
the installed SDK's constructor without ever constructing a client.
"""

import ast
import inspect
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
ENGINE = REPO / "engine"
THE_ONE = "engine/llm/live.py"


def _anthropic_importers() -> list[str]:
    hits = []
    for py in ENGINE.rglob("*.py"):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            if any(n == "anthropic" or n.startswith("anthropic.")
                   for n in names):
                hits.append(str(py.relative_to(REPO)))
                break
    return sorted(set(hits))


def test_only_the_live_caller_imports_the_sdk():
    assert _anthropic_importers() == [THE_ONE], (
        "a second module imports anthropic — every spend path lives in "
        "engine/llm/live.py behind its construction gates")


def test_client_kwargs_pin_timeout_and_no_sdk_retries(monkeypatch):
    monkeypatch.setenv("RFP_LIVE", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-a-real-key")
    from engine.llm.live import DEFAULT_TIMEOUT_S, LiveCaller
    caller = LiveCaller(client=object(), sleep=lambda s: None)
    kwargs = caller._client_kwargs()
    assert kwargs == {"timeout": DEFAULT_TIMEOUT_S, "max_retries": 0}
    assert DEFAULT_TIMEOUT_S == 180.0
    custom = LiveCaller(client=object(), sleep=lambda s: None, timeout_s=30)
    assert custom._client_kwargs()["timeout"] == 30.0
    # the installed SDK's constructor accepts exactly these names
    anthropic = pytest.importorskip("anthropic")
    params = inspect.signature(anthropic.Anthropic.__init__).parameters
    assert set(kwargs) <= set(params)
