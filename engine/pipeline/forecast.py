"""Pre-flight cost forecast (P15/C9, B66 §3): a rough dollar figure for
"what will drafting this pursuit cost?" at gate_0/Gate 1 — the number
the bid/no-bid decision never had. It also answers half of B61's parked
cost-visibility observation.

HONESTY RULES (the rates.yaml discipline, applied forward-looking):
- basis is ALWAYS "estimate" and the payload carries its own
  assumptions — nothing computed here may be shown as a measured
  figure, and the web label must say estimate.
- the unit is named: target_slots when a workbook parses (the honest
  count — parse_workbook is pure code, zero model calls, so it can run
  EARLY), matrix_rows when only the brief exists (cruder, and the
  payload says so).
- prices come from config/models.yaml (the J2-signed table), never
  hardcoded — a re-price moves the forecast automatically.

The call profile is an ASSUMPTION, stated in the payload: per response
unit, roughly one frontier call (planning/audit share), two mid calls
(draft + revise/consistency share), half a fast call (compliance
share), at ~4k input / ~1.2k output tokens each. A1's first real
pursuits are what calibrate it; until then the number is a scale
indicator, not a quote.
"""

from engine.llm.config import model_prices

# calls-per-unit by tier + token assumptions — see module docstring
_PROFILE = {"frontier": 1.5, "mid": 2.0, "fast": 0.5}
_AVG_INPUT_TOKENS = 4000
_AVG_OUTPUT_TOKENS = 1200


def preflight_forecast(*, slot_count: int | None = None,
                       matrix_rows: int | None = None,
                       prices: dict | None = None) -> dict | None:
    """None when there is nothing to count — never a fabricated zero
    (the SupportTrace honesty rule)."""
    if slot_count:
        unit, count = "target_slots", slot_count
    elif matrix_rows:
        unit, count = "matrix_rows", matrix_rows
    else:
        return None
    cfg = prices or model_prices()
    tiers, table = cfg["tiers"], cfg["prices"]
    cost = 0.0
    for tier, calls in _PROFILE.items():
        row = table[tiers[tier]["model"]]
        per_call = (_AVG_INPUT_TOKENS / 1_000_000 * row["input"]
                    + _AVG_OUTPUT_TOKENS / 1_000_000 * row["output"])
        cost += count * calls * per_call
    return {
        "basis": "estimate",
        "unit": unit,
        "unit_count": count,
        "cost_usd_estimate": round(cost, 2),
        "assumptions": {
            "calls_per_unit": dict(_PROFILE),
            "avg_input_tokens": _AVG_INPUT_TOKENS,
            "avg_output_tokens": _AVG_OUTPUT_TOKENS,
            "pricing_as_of": cfg.get("pricing_as_of"),
        },
        "note": ("estimate from a stated call profile — a scale "
                 "indicator for bid/no-bid, never a measured figure; "
                 "A1's real pursuits calibrate it"),
    }
