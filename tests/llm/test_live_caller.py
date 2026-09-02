"""The live caller's refusal gates and transport honesty (B34(19), B30(e)).

Every test is zero-spend: refusals fire before any client exists, and the
transport tests run against a stub Anthropic-shaped object — the stub is
the wire boundary, not a mock of our own code. The construction-refusal
test is the frozen acceptance clause "live caller refuses construction
without RFP_LIVE=1 (proven by test)", with its positive twin FIRST so the
flag is proven to be the deciding variable.
"""

from types import SimpleNamespace

import pytest

from engine.llm.live import (
    LiveCallError,
    LiveCaller,
    OutputTruncated,
    _TransportExhausted,
    coerce_submission,
    load_env_file,
)

KEY = "test-key-not-a-real-credential"


@pytest.fixture
def live_env(monkeypatch):
    monkeypatch.setenv("RFP_LIVE", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)


def _response(result=None, *, stop_reason="tool_use", no_tool=False,
              usage=None):
    content = [] if no_tool else [SimpleNamespace(type="tool_use",
                                                  input={"result": result})]
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=content,
        usage=usage or SimpleNamespace(input_tokens=100, output_tokens=20,
                                       cache_read_input_tokens=0,
                                       cache_creation_input_tokens=0),
    )


class StubClient:
    """Anthropic-shaped: .messages.create pops the next outcome — a response
    to return or an exception to raise — and records every request."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.requests = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _status_error(code):
    exc = RuntimeError(f"api error {code}")
    exc.status_code = code
    return exc


def _caller(client, **kwargs):
    return LiveCaller(client=client, sleep=lambda s: None, **kwargs)


# -- construction gates (the acceptance clause) --------------------------


def test_constructor_constructs_with_rfp_live(live_env):
    # Positive twin first: with the flag and a key, construction succeeds —
    # proving the flag is the deciding variable in the refusal test below.
    caller = _caller(StubClient([]))
    assert caller.config["tiers"]["frontier"]["model"] == "claude-fable-5"


def test_constructor_refuses_without_rfp_live(monkeypatch):
    monkeypatch.delenv("RFP_LIVE", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    with pytest.raises(LiveCallError, match="RFP_LIVE"):
        LiveCaller(client=StubClient([]))


def test_constructor_refuses_without_api_key(monkeypatch):
    monkeypatch.setenv("RFP_LIVE", "1")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(LiveCallError, match="ANTHROPIC_API_KEY"):
        LiveCaller(client=StubClient([]))


def test_constructor_refuses_on_unpriced_model(live_env, tmp_path):
    broken = tmp_path / "models.yaml"
    broken.write_text(
        'pricing_as_of: "2026-08-07"\n'
        "tiers:\n  frontier: {model: m-a, fallback: m-b}\n"
        "prices:\n  m-a: {input: 1.0, output: 2.0, cache_read: 0.1, cache_write: 1.0}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="m-b"):
        LiveCaller(client=StubClient([]), models_yaml=broken)


_DATED_YAML = (
    'pricing_as_of: "2026-08-28"\n'
    'prices_valid_until: "2026-08-31"\n'
    "tiers:\n  frontier: {model: m-a, fallback: m-a}\n"
    "prices:\n  m-a: {input: 1.0, output: 2.0, cache_read: 0.1, cache_write: 1.0}\n"
)


def test_constructor_refuses_on_stale_prices(live_env, tmp_path):
    """B70's staleness guard: a stale price table must REFUSE, because it
    does not fail by itself — it silently under-prices every call and
    loosens every dollar ceiling by the same factor."""
    import datetime

    dated = tmp_path / "models.yaml"
    dated.write_text(_DATED_YAML, encoding="utf-8")
    with pytest.raises(LiveCallError, match="expired 2026-08-31"):
        LiveCaller(client=StubClient([]), models_yaml=dated,
                   today=datetime.date(2026, 9, 1))


def test_constructor_accepts_prices_still_valid(live_env, tmp_path):
    """Positive twin: ON the valid-until date construction succeeds —
    proving the date comparison is the deciding variable above."""
    import datetime

    dated = tmp_path / "models.yaml"
    dated.write_text(_DATED_YAML, encoding="utf-8")
    caller = LiveCaller(client=StubClient([]), models_yaml=dated,
                        today=datetime.date(2026, 8, 31))
    assert caller.config["prices_valid_until"] == "2026-08-31"


# -- transport ------------------------------------------------------------


def test_success_path_forces_the_tool_and_caches_the_system(live_env):
    client = StubClient([_response({"answers": [1, 2]})])
    result = _caller(client).call_for("a", tier="mid", prompt="p", system="SYS")
    assert result.text == '{"answers":[1,2]}'
    assert result.model == "claude-sonnet-5"
    assert result.retries == 0 and result.fell_back_from is None
    request = client.requests[0]
    assert request["tool_choice"] == {"type": "tool", "name": "submit_result"}
    assert request["system"][0]["cache_control"] == {"type": "ephemeral"}


def test_usage_including_cache_tokens_is_extracted(live_env):
    usage = SimpleNamespace(input_tokens=1000, output_tokens=50,
                            cache_read_input_tokens=800,
                            cache_creation_input_tokens=200)
    client = StubClient([_response("plain text", usage=usage)])
    result = _caller(client).call_for("a", tier="fast", prompt="p")
    assert (result.input_tokens, result.output_tokens) == (1000, 50)
    assert (result.cache_read, result.cache_write) == (800, 200)
    assert result.text == "plain text"  # plain strings pass through


def test_stringified_envelope_is_coerced(live_env):
    # v1: found live twice — once with a trailing brace plain json.loads
    # rejects wholesale. raw_decode takes the valid prefix.
    client = StubClient([_response('{"a": 1}}')])
    result = _caller(client).call_for("a", tier="mid", prompt="p")
    assert result.text == '{"a":1}'


def test_truncation_raises_on_attempt_one_never_retried(live_env):
    client = StubClient([_response({"x": 1}, stop_reason="max_tokens")])
    with pytest.raises(OutputTruncated, match="max_tokens"):
        _caller(client).call_for("a", tier="mid", prompt="p")
    assert len(client.requests) == 1


def test_missing_tool_call_is_not_retried(live_env):
    client = StubClient([_response(no_tool=True)])
    with pytest.raises(LiveCallError, match="forced tool_choice"):
        _caller(client).call_for("a", tier="mid", prompt="p")
    assert len(client.requests) == 1


def test_auth_error_surfaces_immediately(live_env):
    client = StubClient([_status_error(401)])
    with pytest.raises(LiveCallError, match="non-transient"):
        _caller(client).call_for("a", tier="mid", prompt="p")
    assert len(client.requests) == 1


def test_transient_backoff_then_success_counts_retries(live_env):
    sleeps = []
    client = StubClient([_status_error(429), _status_error(503),
                         _response({"ok": True})])
    caller = LiveCaller(client=client, sleep=sleeps.append)
    result = caller.call_for("a", tier="mid", prompt="p")
    assert result.retries == 2
    assert sleeps == [2.0, 4.0]
    assert result.model == "claude-sonnet-5"


def test_primary_exhaustion_falls_back_once(live_env):
    client = StubClient([_status_error(429), _status_error(429),
                         _status_error(429), _response({"ok": 1})])
    result = _caller(client).call_for("a", tier="frontier", prompt="p")
    assert result.model == "claude-opus-5"
    assert result.fell_back_from == "claude-fable-5"
    assert result.retries == 2  # the primary's two backoffs, carried
    assert len(client.requests) == 4
    assert [r["model"] for r in client.requests] == (
        ["claude-fable-5"] * 3 + ["claude-opus-5"])


def test_fallback_also_dead_raises_named(live_env):
    client = StubClient([_status_error(429)] * 4)
    with pytest.raises(LiveCallError, match="both exhausted"):
        _caller(client).call_for("a", tier="frontier", prompt="p")
    assert len(client.requests) == 4


# -- P26a Group A: internal vs transport, and the SDK ladder off ---------


def test_internal_error_surfaces_on_attempt_one_without_fallback(live_env):
    """P1-16: an exception with no HTTP status that is NOT the SDK's
    connection/timeout class is our defect — one request, no sleeps, no
    second model, a LiveCallError that says so."""
    sleeps = []
    client = StubClient([TypeError("kwargs built wrong")])
    caller = LiveCaller(client=client, sleep=sleeps.append)
    with pytest.raises(LiveCallError, match="internal error") as e:
        caller.call_for("a", tier="frontier", prompt="p")
    assert "not retried, not fallen back" in str(e.value)
    assert len(client.requests) == 1 and sleeps == []


def test_sdk_connection_and_timeout_errors_are_transient(live_env):
    """The status-less exceptions that ARE transport: the SDK's
    APIConnectionError and its APITimeoutError subclass, retried through
    the ladder like a 503."""
    anthropic = pytest.importorskip("anthropic")
    import httpx
    req = httpx.Request("POST", "https://api.invalid/v1/messages")
    client = StubClient([anthropic.APITimeoutError(request=req),
                         anthropic.APIConnectionError(request=req),
                         _response({"ok": True})])
    sleeps = []
    result = LiveCaller(client=client, sleep=sleeps.append).call_for(
        "a", tier="mid", prompt="p")
    assert result.retries == 2 and sleeps == [2.0, 4.0]
    assert len(client.requests) == 3


def test_builtin_timeout_is_transient_too(live_env):
    client = StubClient([TimeoutError("socket"), _response({"ok": 1})])
    result = _caller(client).call_for("a", tier="fast", prompt="p")
    assert result.retries == 1


# -- coercion unit + env loader ------------------------------------------


def test_coerce_submission_shapes():
    assert coerce_submission({"result": {"a": 1}}) == {"a": 1}
    assert coerce_submission({"result": "[1, 2]"}) == [1, 2]
    assert coerce_submission({"result": "prose answer"}) == "prose answer"
    assert coerce_submission({"result": "{not json"}) == "{not json"


def test_transport_exhausted_is_internal_and_carries_retries():
    exc = _TransportExhausted("dead", retries=2)
    assert isinstance(exc, LiveCallError) and exc.retries == 2


def test_env_loader_fills_gaps_never_overrides(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("# comment\nNEW_VAR_X=from_file\nEXISTING_Y=from_file\n",
                   encoding="utf-8")
    monkeypatch.setenv("EXISTING_Y", "from_env")
    monkeypatch.delenv("NEW_VAR_X", raising=False)
    assert load_env_file(env) is True
    assert __import__("os").environ["NEW_VAR_X"] == "from_file"
    assert __import__("os").environ["EXISTING_Y"] == "from_env"
    monkeypatch.delenv("NEW_VAR_X")
    assert load_env_file(tmp_path / "absent.env") is False
