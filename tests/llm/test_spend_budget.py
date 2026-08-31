"""Runaway-spend guards (recorded decision B41, 2026-08-10).

The per-run ceiling already stopped one expensive run. Two gaps it did
not cover:

  * a walk opens a run per stage and each got a FRESH ceiling, so the
    worst case scaled with stage count rather than being bounded;
  * the dollar ceiling is a slow stop for a CHEAP loop — at a few cents
    a call it takes hundreds of iterations to trip.

SpendBudget closes both, shared across every caller in a walk. Both
limits sit far above anything observed (P8's entire live milestone was
$5.66 across ~60 calls): these are runaway guards, not budgets.
"""

import pytest

from engine.llm import CostCeilingExceeded, FakeCaller, SpendBudget, TracedCaller
from engine.runlog import RunLogger, read_run


def _logger(tmp_path, run_id="run_0001"):
    log = RunLogger(tmp_path / "pur_x", run_id=run_id, pursuit_id="pur_x")
    log.run_start(mode="dry_run", engine_version="0.1.0", config={},
                  kb_snapshot="kb@test")
    return log


class _Priced:
    """A caller whose calls cost real (synthetic) money, so the guards
    have something to count. FakeCaller prices at the synthetic tier
    table, which is deliberately never zero."""

    def __init__(self):
        self.fake = FakeCaller({})

    def call_for(self, agent, *, tier, prompt, system=""):
        return self.fake.call_for(agent, tier=tier, prompt=prompt,
                                  system=system)


def test_budget_is_shared_across_runs_not_reset_per_run(tmp_path):
    """The gap the per-run ceiling left: two runs, one budget."""
    budget = SpendBudget(total_usd=0.05, max_calls=1000)
    first = TracedCaller(_Priced(), _logger(tmp_path, "run_0001"),
                         budget=budget)
    first.call("a", tier="frontier", prompt="p" * 4000)
    spent_after_one = budget.spent_usd
    assert spent_after_one > 0, "the synthetic tier table never prices at zero"

    second = TracedCaller(_Priced(), _logger(tmp_path, "run_0002"),
                          budget=budget)
    with pytest.raises(CostCeilingExceeded) as caught:
        for _ in range(50):
            second.call("a", tier="frontier", prompt="p" * 4000)
    assert "cumulative spend" in str(caught.value)
    assert budget.spent_usd > spent_after_one, "the budget carried over"


def test_call_cap_stops_a_cheap_loop_the_dollar_ceiling_would_not(tmp_path):
    """A loop of tiny calls trips the count long before the dollars —
    which is the whole point: minutes of spin become seconds."""
    budget = SpendBudget(total_usd=1_000_000.0, max_calls=5)
    caller = TracedCaller(_Priced(), _logger(tmp_path), budget=budget)
    with pytest.raises(CostCeilingExceeded) as caught:
        for _ in range(20):
            caller.call("a", tier="fast", prompt="tiny")
    assert "runaway loop" in str(caught.value)
    assert budget.calls == 6, "stops one call past the cap, never earlier"
    assert budget.spent_usd < 1_000_000.0, (
        "the dollar ceiling was nowhere near — the count is what fired")


def test_a_fired_guard_is_a_loud_refusal_on_the_trace(tmp_path):
    """Never a silent truncation: the run log carries why, and the
    message names the override."""
    log = _logger(tmp_path)
    caller = TracedCaller(_Priced(), log, budget=SpendBudget(max_calls=1))
    with pytest.raises(CostCeilingExceeded):
        for _ in range(5):
            caller.call("a", tier="fast", prompt="p")
    errors = [r for r in read_run(log.path) if r["record_type"] == "error"]
    assert errors and errors[-1]["error"]["code"] == "cost_ceiling"
    assert errors[-1]["error"]["action_taken"] == "aborted_run"
    assert "shared budget" in errors[-1]["error"]["message"]


def test_no_budget_means_the_old_behaviour_exactly(tmp_path):
    """The guard is opt-in: every existing caller keeps its per-run
    ceiling and nothing else changes."""
    caller = TracedCaller(_Priced(), _logger(tmp_path))
    assert caller.budget is None
    for _ in range(10):
        caller.call("a", tier="fast", prompt="p")   # no raise


def test_defaults_sit_far_above_observed_usage():
    """P8's whole live milestone was $5.66 across roughly 60 calls. The
    defaults must be runaway guards, not budgets that fire in normal
    work — but not so high they never fire either."""
    budget = SpendBudget()
    assert 20.0 <= budget.total_usd <= 200.0
    assert 100 <= budget.max_calls <= 2000


def test_the_slice_live_path_shares_one_budget():
    """The wiring that matters: every stage's caller in a live walk must
    hold the SAME budget object, or the cross-run guard is decorative."""
    import inspect

    from engine.cli import slice as slice_mod

    source = inspect.getsource(slice_mod.run_slice)
    assert "budget = SpendBudget()" in source
    assert "budget=budget" in source
    assert source.index("budget = SpendBudget()") < source.index("budget=budget"), \
        "the budget must be created OUTSIDE make_caller, or each run gets its own"
