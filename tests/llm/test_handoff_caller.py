"""The handoff caller (P20/B81): request/response files on disk, the
operator as transport. Positive twin FIRST (the live-caller docstring
rule): the answered exchange is proven before any refusal, so the tests
show the seam working, not just failing. Every test runs on an injected
clock and sleep — nothing here waits on a wall clock (B81 D5)."""

import json
import os
from pathlib import Path

import pytest

from engine.llm import (
    CallResult,
    HandoffCaller,
    HandoffError,
    HandoffTimeout,
    TracedCaller,
    cost_usd,
)
from engine.runlog import RunLogger


class _Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _answer(pending: Path, seq: int, **overrides) -> None:
    """Play the operator for one request: derive the response from the
    request file itself, atomic write (tmp + os.replace)."""
    request = json.loads(
        (pending / f"call-{seq:04d}.request.json").read_text(encoding="utf-8"))
    payload = {"seq": request["seq"], "agent": request["agent"],
               "model": "claude-opus-5", "text": f"judged:{request['agent']}"}
    payload.update(overrides)
    target = pending / f"call-{seq:04d}.response.json"
    tmp = pending / (target.name + ".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(tmp, target)


def _caller(tmp_path: Path, *, timeout: float = 10.0, on_sleep=None):
    """A HandoffCaller over an injected clock; on_sleep runs before each
    simulated poll tick (the hook tests use to play the operator)."""
    clock = _Clock()

    def sleep(seconds: float) -> None:
        clock.now += seconds
        if on_sleep is not None:
            on_sleep()

    caller = HandoffCaller(pending_dir=tmp_path / "pending-calls",
                           timeout=timeout, poll=0.5, sleep=sleep,
                           clock=clock)
    return caller, caller.pending_dir


def test_answered_exchange_returns_and_both_files_remain(tmp_path):
    """The positive twin, first: an answered request returns the declared
    text under the handoff/ model prefix, and NEITHER file is deleted —
    the pair on disk is the audit record (B81 D3)."""
    state = {}

    def operator():
        _answer(state["pending"], 1)

    caller, pending = _caller(tmp_path, on_sleep=operator)
    state["pending"] = pending
    result = caller.call_for("claim_auditor", tier="frontier",
                             prompt="judge this", system="you are the auditor")
    assert result.text == "judged:claim_auditor"
    assert result.model == "handoff/claude-opus-5"
    assert (pending / "call-0001.request.json").exists()
    assert (pending / "call-0001.response.json").exists()


def test_request_file_carries_the_full_exchange_context(tmp_path):
    """The request is written BEFORE any waiting, with exactly the fields
    the operator needs — protocol, seq, agent, tier, prompt, system, and
    the (unbound-empty) run correlation ids."""
    seen = {}

    def operator():
        if not seen:
            seen.update(json.loads(
                (seen_dir / "call-0001.request.json").read_text(
                    encoding="utf-8")))
        _answer(seen_dir, 1)

    caller, seen_dir = _caller(tmp_path, on_sleep=operator)
    caller.call_for("section_drafter", tier="mid", prompt="draft it",
                    system="voice rules")
    assert seen == {"protocol": "handoff/v1", "seq": 1,
                    "agent": "section_drafter", "tier": "mid",
                    "prompt": "draft it", "system": "voice rules",
                    "pursuit_id": "", "run_id": ""}


def test_bind_stamps_run_identity_into_requests(tmp_path):
    def operator():
        _answer(pending, 1)

    caller, pending = _caller(tmp_path, on_sleep=operator)
    bound = caller.bind(pursuit_id="pur_x", run_id="run_0007")
    bound.call_for("intake_analyst", tier="frontier", prompt="p")
    request = json.loads(
        (pending / "call-0001.request.json").read_text(encoding="utf-8"))
    assert request["pursuit_id"] == "pur_x"
    assert request["run_id"] == "run_0007"


def test_sequential_calls_write_ordered_pairs(tmp_path):
    state = {"next": 1}

    def operator():
        _answer(pending, state["next"])

    caller, pending = _caller(tmp_path, on_sleep=operator)
    caller.call_for("a", tier="fast", prompt="one")
    state["next"] = 2
    caller.call_for("b", tier="fast", prompt="two")
    names = sorted(p.name for p in pending.iterdir())
    assert names == ["call-0001.request.json", "call-0001.response.json",
                     "call-0002.request.json", "call-0002.response.json"]


def test_construction_resumes_numbering_past_existing_exchanges(tmp_path):
    """A re-advanced walk issues NEW requests — an earlier pair (answered
    or not) is never overwritten."""
    pending = tmp_path / "pending-calls"
    pending.mkdir()
    (pending / "call-0007.request.json").write_text("{}", encoding="utf-8")

    def operator():
        _answer(pending, 8)

    caller, _ = _caller(tmp_path, on_sleep=operator)
    caller.call_for("a", tier="fast", prompt="p")
    assert (pending / "call-0008.request.json").exists()
    assert (pending / "call-0007.request.json").read_text(
        encoding="utf-8") == "{}"


def test_partial_response_keeps_polling_until_valid(tmp_path):
    """A mid-write (unparseable) response is not-ready, never an error —
    the defense against a non-atomic operator write."""
    state = {"ticks": 0}

    def operator():
        state["ticks"] += 1
        target = pending / "call-0001.response.json"
        if state["ticks"] == 1:
            target.write_text('{"seq": 1, "agent": "a", "mo',
                              encoding="utf-8")  # torn write
        else:
            _answer(pending, 1)

    caller, pending = _caller(tmp_path, on_sleep=operator)
    result = caller.call_for("a", tier="fast", prompt="p")
    assert result.text == "judged:a"
    assert state["ticks"] >= 2


def test_echo_mismatch_is_refused_loudly(tmp_path):
    def operator():
        _answer(pending, 1, agent="somebody_else")

    caller, pending = _caller(tmp_path, on_sleep=operator)
    with pytest.raises(HandoffError, match="echo mismatch"):
        caller.call_for("claim_auditor", tier="frontier", prompt="p")


def test_fake_model_declaration_is_refused(tmp_path):
    """A fake- declaration would price the call at the synthetic table —
    fabricated spend on a handoff line (B81 D4)."""
    def operator():
        _answer(pending, 1, model="fake-frontier-1")

    caller, pending = _caller(tmp_path, on_sleep=operator)
    with pytest.raises(HandoffError, match="fake-"):
        caller.call_for("claim_auditor", tier="frontier", prompt="p")


def test_timeout_raises_and_the_request_file_remains(tmp_path):
    """No answer inside the bound: a typed HandoffTimeout naming the
    request file — which stays on disk as the honest record."""
    caller, pending = _caller(tmp_path, timeout=2.0)
    with pytest.raises(HandoffTimeout, match="call-0001.request.json"):
        caller.call_for("claim_auditor", tier="frontier", prompt="p")
    assert (pending / "call-0001.request.json").exists()
    assert not (pending / "call-0001.response.json").exists()


def test_handoff_models_cost_zero_with_and_without_prices(tmp_path):
    """A seat-consumed judgment has no marginal dollar (B81 D4). The
    branch must precede the price-row lookup, or a real model name under
    the handoff/ prefix would raise or misprice."""
    result = CallResult(text="t", model="handoff/claude-opus-5",
                        input_tokens=100_000, output_tokens=100_000)
    assert cost_usd("frontier", result) == 0.0
    assert cost_usd("frontier", result, prices={}) == 0.0


def test_token_counts_honored_when_supplied_else_estimated(tmp_path):
    state = {"next": 1}

    def operator():
        if state["next"] == 1:
            _answer(pending, 1, input_tokens=123, output_tokens=45)
        else:
            _answer(pending, 2)

    caller, pending = _caller(tmp_path, on_sleep=operator)
    counted = caller.call_for("a", tier="fast", prompt="p")
    assert (counted.input_tokens, counted.output_tokens) == (123, 45)
    state["next"] = 2
    estimated = caller.call_for("a", tier="fast", prompt="xxxxxxxx",
                                system="yyyyyyyy")
    assert estimated.input_tokens == max(1, 16 // 4)
    assert estimated.output_tokens == max(1, len(estimated.text) // 4)


def test_traced_handoff_call_lands_as_a_zero_cost_agent_call(tmp_path):
    """The acceptance clause at unit grain: wrapped in TracedCaller, one
    exchange = one agent_call line, model handoff/-prefixed, cost 0.0."""
    def operator():
        _answer(pending, 1)

    caller, pending = _caller(tmp_path, on_sleep=operator)
    log = RunLogger(tmp_path / "pur_t", run_id="run_0001",
                    pursuit_id="pur_t")
    traced = TracedCaller(caller.bind(pursuit_id="pur_t",
                                      run_id="run_0001"), log)
    traced.call("claim_auditor", tier="frontier", prompt="judge",
                stage="validation")
    records = [json.loads(line) for line in
               log.path.read_text(encoding="utf-8").splitlines()]
    assert [r["record_type"] for r in records] == ["agent_call"]
    assert records[0]["model"] == "handoff/claude-opus-5"
    assert records[0]["cost_usd"] == 0.0
    assert records[0]["model_tier"] == "frontier"
