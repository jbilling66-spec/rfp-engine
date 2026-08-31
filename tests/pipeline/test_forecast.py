"""The pre-flight cost forecast (P15/C9): honestly labeled, unit named,
priced from the J2-signed table, None-before-anything (never a
fabricated zero)."""

from engine.pipeline.forecast import preflight_forecast

PRICES = {
    "pricing_as_of": "2026-08-28",
    "tiers": {"frontier": {"model": "m-f", "fallback": "m-f"},
              "mid": {"model": "m-m", "fallback": "m-f"},
              "fast": {"model": "m-s", "fallback": "m-m"}},
    "prices": {
        "m-f": {"input": 10.0, "output": 50.0,
                "cache_read": 1.0, "cache_write": 12.5},
        "m-m": {"input": 3.0, "output": 15.0,
                "cache_read": 0.3, "cache_write": 3.75},
        "m-s": {"input": 1.0, "output": 5.0,
                "cache_read": 0.1, "cache_write": 1.25},
    },
}


def test_nothing_to_count_is_none_never_zero():
    assert preflight_forecast(prices=PRICES) is None


def test_slot_count_beats_matrix_rows_and_math_is_stated():
    out = preflight_forecast(slot_count=19, matrix_rows=4, prices=PRICES)
    assert out["unit"] == "target_slots" and out["unit_count"] == 19
    assert out["basis"] == "estimate"
    # the arithmetic follows the STATED assumptions exactly
    a = out["assumptions"]
    per = {t: (a["avg_input_tokens"] / 1e6 * PRICES["prices"][m]["input"]
               + a["avg_output_tokens"] / 1e6 * PRICES["prices"][m]["output"])
           for t, m in (("frontier", "m-f"), ("mid", "m-m"), ("fast", "m-s"))}
    expected = sum(19 * a["calls_per_unit"][t] * per[t] for t in per)
    assert abs(out["cost_usd_estimate"] - expected) <= 0.01
    assert a["pricing_as_of"] == "2026-08-28"
    assert "never a measured figure" in out["note"]


def test_matrix_fallback_is_named_cruder_by_its_unit():
    out = preflight_forecast(matrix_rows=7, prices=PRICES)
    assert out["unit"] == "matrix_rows" and out["unit_count"] == 7


def test_committed_price_table_prices_the_forecast():
    # against the real models.yaml — a re-price moves this automatically
    out = preflight_forecast(slot_count=10)
    assert out["cost_usd_estimate"] > 0
    assert out["assumptions"]["pricing_as_of"] == "2026-08-28"
