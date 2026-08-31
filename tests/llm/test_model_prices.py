"""config/models.yaml price-table completeness (B34(21), B29(a)(2)).

The committed file must price every model the tier router can reach —
tier models AND fallbacks — with all four components, because a fallback
call bills at the fallback's rates and an unpriced reachable model is the
silent-cost-corruption path B29(a)(2) reclassified as BLOCKING. The loader
is the contract: every malformation raises, loudly, naming the defect.
"""

import pytest

from engine.llm import model_prices

GOOD = """\
pricing_as_of: "2026-08-07"
tiers:
  frontier: {model: m-front, fallback: m-fall}
prices:
  m-front: {input: 1.0, output: 2.0, cache_read: 0.1, cache_write: 1.25}
  m-fall: {input: 0.5, output: 1.0, cache_read: 0.05, cache_write: 0.625}
"""


def test_committed_models_yaml_is_complete_and_priced():
    loaded = model_prices()
    assert loaded["pricing_as_of"] == "2026-08-28"  # B70 re-sign (J2)
    # The B70 re-price: sonnet-5 at STANDARD rates — a regression to the
    # expired introductory numbers would under-price every mid-tier call
    # and loosen every dollar ceiling by the same factor.
    assert loaded["prices"]["claude-sonnet-5"] == {
        "input": 3.00, "output": 15.00,
        "cache_read": 0.30, "cache_write": 3.75}
    reachable = {
        entry[role]
        for entry in loaded["tiers"].values()
        for role in ("model", "fallback")
    }
    # Every reachable model priced with all four components (the loader
    # enforces it; restated here so the property is visible at the test).
    for model in reachable:
        row = loaded["prices"][model]
        assert set(row) == {"input", "output", "cache_read", "cache_write"}
        assert all(value >= 0 for value in row.values())
    # The three tier primaries are the N5 pins.
    tiers = loaded["tiers"]
    assert tiers["frontier"]["model"] == "claude-fable-5"
    assert tiers["mid"]["model"] == "claude-sonnet-5"
    assert tiers["fast"]["model"] == "claude-haiku-4-5-20251001"


def _write(tmp_path, text):
    path = tmp_path / "models.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_valid_shape_loads(tmp_path):
    loaded = model_prices(_write(tmp_path, GOOD))
    assert loaded["prices"]["m-fall"]["cache_write"] == 0.625


def test_unpriced_fallback_raises(tmp_path):
    broken = GOOD.replace("  m-fall: {input: 0.5, output: 1.0, cache_read: 0.05, cache_write: 0.625}\n", "")
    with pytest.raises(ValueError, match="m-fall"):
        model_prices(_write(tmp_path, broken))


def test_partial_price_row_raises(tmp_path):
    broken = GOOD.replace(
        "m-front: {input: 1.0, output: 2.0, cache_read: 0.1, cache_write: 1.25}",
        "m-front: {input: 1.0, output: 2.0}",
    )
    with pytest.raises(ValueError, match="m-front"):
        model_prices(_write(tmp_path, broken))


def test_negative_price_raises(tmp_path):
    broken = GOOD.replace("input: 1.0", "input: -1.0")
    with pytest.raises(ValueError, match="non-negative"):
        model_prices(_write(tmp_path, broken))


def test_missing_pricing_as_of_raises(tmp_path):
    broken = GOOD.replace('pricing_as_of: "2026-08-07"\n', "")
    with pytest.raises(ValueError, match="pricing_as_of"):
        model_prices(_write(tmp_path, broken))


def test_prices_valid_until_optional_but_shape_checked(tmp_path):
    """B70: the dated-pricing marker is optional; when present it must be a
    real YYYY-MM-DD (the LiveCaller guard parses it — a typo'd date must
    fail at load, not at the moment of the first live run)."""
    dated = GOOD + 'prices_valid_until: "2026-12-31"\n'
    assert model_prices(_write(tmp_path, dated))[
        "prices_valid_until"] == "2026-12-31"
    with pytest.raises(ValueError, match="prices_valid_until"):
        model_prices(_write(tmp_path, GOOD + 'prices_valid_until: "soon"\n'))
