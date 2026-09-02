"""The transport stub's shape is pinned against the installed SDK
(P26a Group A — P2-15): a REAL anthropic.types.Message flows through
LiveCaller._parse and every keyword _request sends is a parameter of
Messages.create. No client is built, nothing is called, nothing is
spent — the types are pydantic models constructed offline."""

import inspect

import pytest

anthropic = pytest.importorskip("anthropic")
from anthropic.resources.messages import Messages  # noqa: E402
from anthropic.types import Message, ToolUseBlock, Usage  # noqa: E402

from engine.llm.live import LiveCaller  # noqa: E402


@pytest.fixture
def caller(monkeypatch):
    monkeypatch.setenv("RFP_LIVE", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-a-real-key")
    return LiveCaller(client=object(), sleep=lambda s: None)


def _message(**usage):
    return Message(
        id="msg_synthetic", model="claude-synthetic", role="assistant",
        type="message", stop_reason="tool_use", stop_sequence=None,
        content=[ToolUseBlock(id="tu_1", name="submit_result",
                              input={"result": {"answer": 1}},
                              type="tool_use")],
        usage=Usage(input_tokens=usage.get("input_tokens", 10),
                    output_tokens=usage.get("output_tokens", 2),
                    cache_read_input_tokens=usage.get("cache_read", 0),
                    cache_creation_input_tokens=usage.get("cache_write", 0)))


def test_a_real_sdk_message_parses_with_cache_counters(caller):
    result = caller._parse(_message(cache_read=7, cache_write=5), "m",
                           retries=0)
    assert result.text == '{"answer":1}'
    assert (result.input_tokens, result.output_tokens) == (10, 2)
    assert (result.cache_read, result.cache_write) == (7, 5), (
        "cache counters are READ from the SDK object, never defaulted")


def test_every_request_keyword_is_a_create_parameter(caller):
    sent = {}

    class Recorder:
        class messages:  # noqa: N801 — mirrors the SDK attribute
            @staticmethod
            def create(**kwargs):
                sent.update(kwargs)
                return _message()

    caller._request(Recorder(), "m", "prompt", "system text")
    params = inspect.signature(Messages.create).parameters
    unknown = sorted(set(sent) - set(params))
    assert not unknown, f"_request sends keywords create() lacks: {unknown}"
    assert {"model", "max_tokens", "messages", "tools", "tool_choice",
            "system"} <= set(sent)


def test_the_sdk_attributes_the_parser_reads_exist():
    m = _message()
    assert m.stop_reason == "tool_use"
    assert m.content[0].type == "tool_use" and m.content[0].input
    for name in ("input_tokens", "output_tokens",
                 "cache_read_input_tokens", "cache_creation_input_tokens"):
        assert hasattr(m.usage, name), name
