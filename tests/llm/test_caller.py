"""TracedCaller: no call escapes the trace; the ceiling aborts loudly;
a prompt edit changes config_digest (P0 acceptance). P8 additions
(sanctioned in the plan): per-model four-component pricing, cache/retry
emission, and the fallback error line (B34(20))."""

import pytest

from engine.llm import (
    CallResult,
    CostCeilingExceeded,
    FakeCaller,
    TracedCaller,
    cost_usd,
    effective_config,
)
from engine.runlog import RunLogger, config_digest, read_run


@pytest.fixture
def log(tmp_path):
    return RunLogger(tmp_path / "pur_t", run_id="run_0001", pursuit_id="pur_t")


def test_every_call_lands_in_the_trace(log):
    caller = TracedCaller(FakeCaller({"a": "hello world"}), log)
    result = caller.call("a", tier="mid", prompt="do a thing", stage="drafting",
                         section_id="s1")
    records = read_run(log.path)
    assert len(records) == 1
    rec = records[0]
    assert rec["record_type"] == "agent_call"
    assert rec["model"] == result.model == "fake-mid-1"
    assert rec["cost_usd"] > 0
    assert rec["target"] == {"section_id": "s1"}
    assert "do a thing" not in log.path.read_text()  # prompts never enter the log


def test_ceiling_aborts_and_logs_the_error(log):
    caller = TracedCaller(FakeCaller({"a": "x" * 4000}), log, ceiling_usd=0.00001)
    with pytest.raises(CostCeilingExceeded):
        caller.call("a", tier="frontier", prompt="p")
    kinds = [r["record_type"] for r in read_run(log.path)]
    assert kinds == ["agent_call", "error"]


def test_prompt_edit_changes_config_digest(tmp_path):
    prompts = tmp_path / "prompts"
    (prompts / "agent_x").mkdir(parents=True)
    (prompts / "agent_x" / "prompt.md").write_text("v1 prompt\n")
    models = tmp_path / "models.yaml"
    models.write_text("tiers: {mid: {model: m1}}\n")

    before = config_digest(effective_config(prompts_dir=prompts, models_yaml=models))
    (prompts / "agent_x" / "prompt.md").write_text("v2 prompt — edited\n")
    after = config_digest(effective_config(prompts_dir=prompts, models_yaml=models))
    assert before != after

    models.write_text("tiers: {mid: {model: m2}}\n")
    assert config_digest(
        effective_config(prompts_dir=prompts, models_yaml=models)
    ) != after  # model repin also changes the digest (N5)


PRICES = {"real-model-1": {"input": 10.0, "output": 50.0,
                           "cache_read": 1.0, "cache_write": 12.5}}


def _result(**over):
    base = dict(text="t", model="real-model-1", input_tokens=1_000_000,
                output_tokens=100_000)
    base.update(over)
    return CallResult(**base)


def test_per_model_pricing_uses_all_four_components():
    result = _result(cache_read=500_000, cache_write=200_000)
    # 1M*10 + 0.1M*50 + 0.5M*1 + 0.2M*12.5 per Mtok
    assert cost_usd("frontier", result, PRICES) == pytest.approx(
        10.0 + 5.0 + 0.5 + 2.5)


def test_unpriced_nonfake_model_raises():
    with pytest.raises(ValueError, match="no price row"):
        cost_usd("frontier", _result(model="mystery-model"), PRICES)


def test_fake_models_keep_synthetic_prices_even_with_a_price_table():
    result = CallResult(text="t", model="fake-mid-1",
                        input_tokens=1_000_000, output_tokens=0)
    assert cost_usd("mid", result, PRICES) == pytest.approx(3.0)


class _StubCaller:
    """A CallerFor that returns a canned live-shaped result."""

    def __init__(self, result):
        self.result = result

    def call_for(self, agent, *, tier, prompt, system=""):
        return self.result


def test_cache_retry_and_fallback_reach_the_trace(log):
    result = _result(cache_read=400, cache_write=100, retries=2,
                     fell_back_from="primary-model-1")
    caller = TracedCaller(_StubCaller(result), log, prices=PRICES)
    caller.call("a", tier="frontier", prompt="p", stage="validation")
    records = read_run(log.path)
    call, fallback = records
    assert call["tokens"] == {"input": 1_000_000, "output": 100_000,
                              "cache_read": 400, "cache_write": 100}
    assert call["retries"] == 2
    assert fallback["record_type"] == "error"
    assert fallback["error"]["action_taken"] == "fell_back_model"
    assert "primary-model-1" in fallback["error"]["message"]


def test_zero_cache_and_retries_stay_off_the_line(log):
    caller = TracedCaller(FakeCaller({"a": "hi"}), log)
    caller.call("a", tier="mid", prompt="p")
    rec = read_run(log.path)[0]
    assert set(rec["tokens"]) == {"input", "output"}
    assert "retries" not in rec
