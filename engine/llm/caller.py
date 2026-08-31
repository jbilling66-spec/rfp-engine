"""The model-call boundary. Every model interaction goes through a
TracedCaller, which emits the agent_call run-log line itself — a call that
escapes the trace is structurally impossible, not a discipline.

FakeCaller is the default everywhere (zero spend, deterministic). The live
caller (engine/llm/live.py, P8) refuses construction without RFP_LIVE=1 —
wired through live_allowed() below and proven by test (B30(e)). The cost
ceiling is N6: a run that exceeds its budget aborts loudly instead of
burning quietly. Pricing: a per-model row from config/models.yaml prices the
four token components; fake-* models keep the synthetic tier table; a
non-fake model with no row RAISES — a live call must never silently price
at synthetic rates (B34(20)).
"""

import os
import time
from dataclasses import dataclass, field
from typing import Callable, Protocol

from engine.runlog import RunLogger


class CostCeilingExceeded(RuntimeError):
    pass


@dataclass
class CallResult:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_read: int = 0
    cache_write: int = 0
    retries: int = 0
    fell_back_from: str | None = None


class CallerFor(Protocol):
    """The interface TracedCaller wraps — FakeCaller and LiveCaller both
    expose it. The agent name keys prompt-registry dispatch and the trace."""

    def call_for(self, agent: str, *, tier: str, prompt: str,
                 system: str = "") -> CallResult: ...


# Synthetic per-Mtok prices so the cost meter is exercised deterministically
# offline. Real prices come per-model from config/models.yaml (model_prices).
_FAKE_PRICES = {"frontier": (15.0, 75.0), "mid": (3.0, 15.0), "fast": (1.0, 5.0)}


@dataclass
class FakeCaller:
    """Deterministic offline double. `script` maps agent name -> response
    text (or a callable of the prompt); unscripted agents echo a stub."""

    script: dict[str, str | Callable[[str], str]] = field(default_factory=dict)

    def call_for(self, agent: str, *, tier: str, prompt: str, system: str = "") -> CallResult:
        entry = self.script.get(agent, f"[fake:{agent}] ok")
        text = entry(prompt) if callable(entry) else entry
        return CallResult(
            text=text,
            model=f"fake-{tier}-1",
            input_tokens=max(1, (len(system) + len(prompt)) // 4),
            output_tokens=max(1, len(text) // 4),
        )


def cost_usd(tier: str, result: CallResult, prices: dict | None = None) -> float:
    """Per-call cost. With a per-model price row ({input, output, cache_read,
    cache_write} USD/MTok — the models.yaml shape), the four-component
    formula applies. fake-* models price at the synthetic tier table even
    when a prices dict is supplied (dry runs must stay deterministic and
    never bill at real rates); a non-fake model without a row raises.
    handoff/* models cost 0.0 unconditionally — a seat-consumed judgment
    has no marginal dollar, and pricing its real model name at either
    table would fabricate spend (P20/B81 D4, B34(20)'s mirror)."""
    if result.model.startswith("handoff/"):
        return 0.0
    if prices is not None and not result.model.startswith("fake-"):
        row = prices.get(result.model)
        if row is None:
            raise ValueError(
                f"model {result.model!r} has no price row — an unpriced live "
                f"call must never price at synthetic rates (B34(20))")
        return round(
            result.input_tokens * row["input"] / 1_000_000
            + result.output_tokens * row["output"] / 1_000_000
            + result.cache_read * row["cache_read"] / 1_000_000
            + result.cache_write * row["cache_write"] / 1_000_000,
            6,
        )
    per_in, per_out = _FAKE_PRICES[tier]
    return round(
        result.input_tokens * per_in / 1_000_000
        + result.output_tokens * per_out / 1_000_000,
        6,
    )


@dataclass
class SpendBudget:
    """A ceiling that outlives a single run (recorded decision, 2026-08-10).

    The per-run ceiling on TracedCaller stops one expensive run, but a
    pipeline opens a run per stage and each got a fresh ceiling — so the
    worst case scaled with stage count rather than being bounded. This
    object is shared across every caller in a walk and bounds the whole
    thing.

    max_calls exists because the dollar ceiling is a slow stop for a
    CHEAP loop: at a few cents a call it takes hundreds of iterations to
    trip, which is minutes of spin. A call count catches that in
    seconds. Both are deliberately far above anything observed (the
    entire P8 live milestone was $5.66 across ~60 calls) — they are
    runaway guards, not budgets, and a fired guard is a loud refusal
    naming the override, never a silent truncation."""

    total_usd: float = 50.0
    max_calls: int = 400
    spent_usd: float = 0.0
    calls: int = 0

    def record(self, cost: float) -> None:
        self.spent_usd = round(self.spent_usd + cost, 6)
        self.calls += 1

    def breach(self) -> str | None:
        if self.spent_usd > self.total_usd:
            return (f"cumulative spend {self.spent_usd} exceeded the shared "
                    f"budget {self.total_usd}")
        if self.calls > self.max_calls:
            return (f"{self.calls} model calls exceeded the shared cap "
                    f"{self.max_calls} — a runaway loop, not a workload")
        return None


@dataclass
class TracedCaller:
    """Wraps a caller with the run log and the cost ceiling. This is the only
    interface stages are given — prompts never reach the log (digests do,
    via the logger's own discipline), and spend is metered per run."""

    caller: CallerFor
    log: RunLogger
    ceiling_usd: float = 25.0
    spent_usd: float = 0.0
    prices: dict | None = None
    budget: SpendBudget | None = None

    def call(self, agent: str, *, tier: str, prompt: str, system: str = "",
             stage: str | None = None, span_id: str | None = None,
             parent_span: str | None = None, **target) -> CallResult:
        started = time.perf_counter()
        result = self.caller.call_for(agent, tier=tier, prompt=prompt, system=system)
        # duration_ms was schema-declared with no writer, which left
        # run.totals.compute_ms unsourceable and compute_vs_human_wait
        # (O6) dormant. Measured here because this is the only place the
        # call actually happens; a stage-level timer would fold queueing
        # and bookkeeping into "compute".
        duration_ms = int((time.perf_counter() - started) * 1000)
        call_cost = cost_usd(tier, result, self.prices)
        self.spent_usd = round(self.spent_usd + call_cost, 6)
        tokens = {"input": result.input_tokens, "output": result.output_tokens}
        if result.cache_read:
            tokens["cache_read"] = result.cache_read
        if result.cache_write:
            tokens["cache_write"] = result.cache_write
        fields = {
            "agent": agent,
            "model": result.model,
            "model_tier": tier,
            "tokens": tokens,
            "cost_usd": call_cost,
            "duration_ms": duration_ms,
        }
        if result.retries:
            fields["retries"] = result.retries
        if stage:
            fields["stage"] = stage
        if span_id:
            fields["span_id"] = span_id
        if parent_span:
            fields["parent_span"] = parent_span
        if target:
            fields["target"] = target
        self.log.emit("agent_call", **fields)
        if result.fell_back_from:
            self.log.emit("error", error={
                "code": "model_fallback",
                "message": (f"primary {result.fell_back_from} exhausted transport "
                            f"retries; fell back to {result.model} (N5)"),
                "recoverable": True,
                "action_taken": "fell_back_model",
            })
        if self.spent_usd > self.ceiling_usd:
            self.log.emit("error", error={
                "code": "cost_ceiling",
                "message": f"run spend {self.spent_usd} exceeded ceiling {self.ceiling_usd}",
                "recoverable": False,
                "action_taken": "aborted_run",
            })
            raise CostCeilingExceeded(
                f"spent {self.spent_usd} > ceiling {self.ceiling_usd} (N6)"
            )
        if self.budget is not None:
            self.budget.record(call_cost)
            breach = self.budget.breach()
            if breach:
                self.log.emit("error", error={
                    "code": "cost_ceiling",
                    "message": f"shared budget: {breach}",
                    "recoverable": False,
                    "action_taken": "aborted_run",
                })
                raise CostCeilingExceeded(
                    f"{breach} — raise it deliberately and re-run (N6)")
        return result


def live_allowed() -> bool:
    return os.environ.get("RFP_LIVE") == "1"
