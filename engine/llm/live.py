"""LiveCaller — the only code path that can ever bill money (P8, B34(19)).

Construction refuses three ways, each named, each proven by test, each
BEFORE any client exists (a refused construction spends nothing):
  1. RFP_LIVE=1 absent — live_allowed(), the B30(e) acceptance clause;
  2. an incomplete price table — model_prices() raises (B29(a)(2) made
     structural: an unpriced reachable model must not be constructable);
  3. ANTHROPIC_API_KEY absent — named refusal (v1 EC-12: a broken env
     loader once masked this until after real spend was attempted).

Transport honesty (v1 lineage, adapted): structured output is a FORCED
submit_result tool call; stringified envelopes are coerced via raw_decode
(found live twice in v1, once with a trailing brace that json.loads
rejects wholesale); truncation is detected on attempt ONE via stop_reason
and never retried (a config problem — the same ceiling truncates
identically); 4xx except 408/429 surface immediately; transient errors get
three attempts with exponential backoff, counted on the CallResult and
echoed to stderr so retries are never invisible; after primary transport
exhaustion, ONE attempt at the tier's fallback model (N5's tested-fallback
demand — the fallback path is exercised under a stub client in the suite).

Timeouts and retry honesty (P26a Group A — P0-1, P1-16): every request
carries an explicit timeout (DEFAULT_TIMEOUT_S; the SDK's adaptive
ten-minute default switches off under it), the SDK's own retry ladder is
OFF (max_retries=0) so ours is the only one and CallResult.retries counts
every retry that happened, and an exception with no HTTP status is a
TRANSPORT error only when it is the SDK's connection/timeout class — any
other status-less exception is an internal defect, surfaced on attempt
one, never retried, never fallen back (an internal bug must not become
extra spend).

Deliberately absent, each with its closer: circuit breakers -> A6;
rate-limit strategy beyond backoff -> A6; validation-error feedback
loops -> stages own pend-and-report (B34(19), revisit at P9).
"""

import datetime
import json
import os
import sys
from dataclasses import replace
from pathlib import Path

from engine.llm.caller import CallResult, live_allowed
from engine.llm.config import MODELS_YAML, model_prices


def _is_transport_error(exc: BaseException) -> bool:
    """The SDK's connection/timeout errors carry no status and ARE
    transient; everything else status-less is not (P1-16)."""
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True
    try:
        import anthropic  # deferred, like _get_client
    except ImportError:  # pragma: no cover — the live path cannot run then
        return False
    return isinstance(exc, anthropic.APIConnectionError)


class LiveCallError(RuntimeError):
    """A live call (or its construction) failed in a way retrying cannot fix."""


class OutputTruncated(LiveCallError):
    """stop_reason == max_tokens: a CONFIG problem, never retried — the same
    ceiling truncates the same prompt identically."""


class _TransportExhausted(LiveCallError):
    """Internal: the primary model's transport attempts are spent."""

    def __init__(self, message: str, retries: int):
        super().__init__(message)
        self.retries = retries


_BACKOFFS = (2.0, 4.0)  # three attempts total: try, +2s, +4s

# P0-1: one request's wall-clock ceiling. max_tokens=8192 at a slow
# ~60 tok/s is ~140s; 180s leaves queueing headroom without letting a
# hung socket wedge the single job worker for the SDK's ten minutes.
# One line + a B-entry to change (the upload-cap precedent, P25 item 6).
DEFAULT_TIMEOUT_S = 180.0

_SUBMIT_TOOL = {
    "name": "submit_result",
    "description": "Submit the final result. The result field carries the "
                   "complete answer in the exact shape the task demands.",
    "input_schema": {
        "type": "object",
        "properties": {"result": {}},
        "required": ["result"],
    },
}


def coerce_submission(value):
    """The forced tool's input -> the result payload. Models sometimes
    JSON-encode the nested result as a string; raw_decode accepts a valid
    prefix (surviving trailing-brace garbage) and only containers are
    taken — anything else stays the string it was."""
    result = value.get("result") if isinstance(value, dict) else value
    if isinstance(result, str) and result.strip()[:1] in ("{", "["):
        try:
            decoded, _ = json.JSONDecoder().raw_decode(result.strip())
        except ValueError:
            return result
        if isinstance(decoded, (dict, list)):
            return decoded
    return result


def load_env_file(path: Path) -> bool:
    """Tiny stdlib .env loader (B34(22)). KEY=VALUE lines; the EXISTING
    environment always wins — .env fills gaps, never overrides; values are
    only placed into os.environ, never stored or logged. Called ONLY by the
    slice CLI's --live path; library code never reads .env."""
    if not path.exists():
        return False
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if key and key not in os.environ:
            os.environ[key] = value
    return True


class LiveCaller:
    """CallerFor over the Anthropic Messages API. Wrap in TracedCaller with
    prices=model_prices()["prices"] — an untraced live call must not exist."""

    def __init__(self, *, models_yaml: Path = MODELS_YAML, client=None,
                 max_tokens: int = 8192, sleep=None, today=None,
                 timeout_s: float = DEFAULT_TIMEOUT_S):
        if not live_allowed():
            raise LiveCallError(
                "live caller refused construction: RFP_LIVE=1 is not set "
                "(B30(e)). Nothing was constructed and nothing was called.")
        self.config = model_prices(models_yaml)  # raises on any unpriced model
        valid_until = self.config.get("prices_valid_until")
        if valid_until is not None:
            # The staleness guard (B70): a stale price table does not refuse
            # by itself — it silently under-prices every call and loosens
            # every dollar ceiling by the same factor. The clock read lives
            # HERE, on the spend path only (B19(8): library code never reads
            # the wall clock; dry runs stay byte-deterministic).
            today = today or datetime.date.today()
            if today > datetime.date.fromisoformat(str(valid_until)):
                raise LiveCallError(
                    f"live caller refused construction: models.yaml prices "
                    f"expired {valid_until} (today {today.isoformat()}). "
                    f"Re-price and re-sign (J2) before any live run — a "
                    f"stale table bills silently at the wrong rates. "
                    f"Nothing was called.")
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise LiveCallError(
                "live caller refused construction: ANTHROPIC_API_KEY is absent "
                "from the environment. Nothing was called.")
        self._client = client  # injectable; the real one is built lazily
        self.max_tokens = max_tokens
        self.timeout_s = float(timeout_s)
        self._sleep = sleep if sleep is not None else __import__("time").sleep

    # -- transport ---------------------------------------------------------

    def _client_kwargs(self) -> dict:
        """P0-1 / P1-16: the explicit timeout, and NO SDK-side retries —
        our ladder is the only one, so `retries` on the CallResult (the
        registered retry_rate metric's sole input) counts every retry."""
        return {"timeout": self.timeout_s, "max_retries": 0}

    def _get_client(self):
        if self._client is None:
            import anthropic  # deferred: the suite never needs the package wired

            self._client = anthropic.Anthropic(**self._client_kwargs())
        return self._client

    def _request(self, client, model: str, prompt: str, system: str):
        kwargs = {
            "model": model,
            "max_tokens": self.max_tokens,
            "messages": [{"role": "user", "content": prompt}],
            "tools": [_SUBMIT_TOOL],
            "tool_choice": {"type": "tool", "name": "submit_result"},
        }
        if system:
            # One cache breakpoint on the stable per-stage system block —
            # v1 shipped its API path with cache_read=0 for months.
            kwargs["system"] = [{"type": "text", "text": system,
                                "cache_control": {"type": "ephemeral"}}]
        return client.messages.create(**kwargs)

    def _parse(self, response, model: str, *, retries: int) -> CallResult:
        if getattr(response, "stop_reason", None) == "max_tokens":
            raise OutputTruncated(
                f"{model}: output truncated at max_tokens={self.max_tokens} — "
                f"a config problem, not retried (raise the ceiling or shrink "
                f"the task)")
        block = next((b for b in response.content
                      if getattr(b, "type", None) == "tool_use"), None)
        if block is None:
            raise LiveCallError(
                f"{model}: no tool_use block despite forced tool_choice — "
                f"absence is not retryable")
        payload = coerce_submission(block.input)
        text = (payload if isinstance(payload, str)
                else json.dumps(payload, separators=(",", ":"), sort_keys=True))
        usage = getattr(response, "usage", None)

        def _tok(name):
            return getattr(usage, name, 0) or 0

        return CallResult(
            text=text,
            model=model,
            input_tokens=_tok("input_tokens"),
            output_tokens=_tok("output_tokens"),
            cache_read=_tok("cache_read_input_tokens"),
            cache_write=_tok("cache_creation_input_tokens"),
            retries=retries,
        )

    def _call_model(self, model: str, *, prompt: str, system: str,
                    attempts: int, retries_base: int = 0) -> CallResult:
        client = self._get_client()
        retries = retries_base
        for attempt in range(attempts):
            try:
                response = self._request(client, model, prompt, system)
            except Exception as exc:  # only the client call is inside the try
                status = getattr(exc, "status_code", None)
                if status is None and not _is_transport_error(exc):
                    # P1-16: no HTTP status and not the SDK's connection or
                    # timeout class = OUR defect, surfaced on attempt one —
                    # never retried through the ladder, never fallen back
                    raise LiveCallError(
                        f"{model}: internal error before the request "
                        f"completed ({type(exc).__name__}: {exc}) — not "
                        f"retried, not fallen back") from exc
                transient = (status in (408, 429)
                             or (isinstance(status, int) and status >= 500)
                             or status is None)
                if not transient:
                    raise LiveCallError(
                        f"{model}: non-transient API error (status {status}) — "
                        f"surfaced immediately, never retried") from exc
                if attempt < attempts - 1:
                    delay = _BACKOFFS[min(attempt, len(_BACKOFFS) - 1)]
                    sys.stderr.write(
                        f"live retry {attempt + 1}/{attempts - 1} for {model} "
                        f"in {delay}s: {exc}\n")
                    self._sleep(delay)
                    retries += 1
                    continue
                raise _TransportExhausted(
                    f"{model}: transport exhausted after {attempts} attempt(s)",
                    retries=retries) from exc
            return self._parse(response, model, retries=retries)
        raise AssertionError("unreachable")

    # -- the CallerFor surface --------------------------------------------

    def call_for(self, agent: str, *, tier: str, prompt: str,
                 system: str = "") -> CallResult:
        entry = self.config["tiers"][tier]
        primary, fallback = entry["model"], entry["fallback"]
        try:
            return self._call_model(primary, prompt=prompt, system=system,
                                    attempts=1 + len(_BACKOFFS))
        except _TransportExhausted as exhausted:
            try:
                result = self._call_model(fallback, prompt=prompt, system=system,
                                          attempts=1,
                                          retries_base=exhausted.retries)
            except _TransportExhausted as also_dead:
                raise LiveCallError(
                    f"tier {tier!r}: primary {primary} and fallback {fallback} "
                    f"both exhausted transport retries") from also_dead
            return replace(result, fell_back_from=primary)
