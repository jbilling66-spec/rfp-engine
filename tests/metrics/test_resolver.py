"""The metric resolver (c14) and two frozen acceptance clauses:
"unknown metric_id fails build" and "bench runs leave aggregates
unchanged".

Every expected value below is computed BY HAND from the committed
fixture pursuit, never by running the resolver and pasting its answer —
otherwise the test would prove only that the code is consistent with
itself.
"""

import json
from pathlib import Path

import pytest

from engine.metrics.resolver import (RESOLVERS, Corpus, UnknownMetric,
                                     load_registry, resolve, resolve_all)
from engine.metrics.views import VIEWS, render_view, validate_views

FIXTURE_WS = Path(__file__).resolve().parents[1] / "fixtures" / "pursuits"


@pytest.fixture(scope="module")
def corpus():
    return Corpus(FIXTURE_WS)


@pytest.fixture(scope="module")
def registry():
    return load_registry()


# ------------------------------------------------- registry <-> resolver

def test_every_registry_metric_has_a_resolver_slot(registry):
    """The bijection. A new metric_id cannot land unresolvable, and a
    resolver cannot outlive the registry entry it serves."""
    assert set(RESOLVERS) == set(registry)
    assert len(registry) == 36, \
        "the pin moved 30->35 at P13/C18 (B51's five §A6 metrics), 36 at P26a (P0-15)"


def test_unresolved_slots_are_named_not_forgotten(registry):
    """Some metrics have no resolver yet. Each must be a deliberate None
    with an honest reason at the slot, not a missing key."""
    unresolved = sorted(k for k, v in RESOLVERS.items() if v is None)
    assert unresolved == [
        "extraction_seconds_per_page",  # timing excluded from artifacts
        #   for kill/resume byte-identity; A1 instruments live runs
        "extraction_table_fidelity",  # bench/gate release record class,
        #   wired at A1's real-corpus rerun
    ]


# ------------------------------------------------- hand-computed values

def test_engine_cost_per_pursuit_excludes_the_bench_run(corpus):
    """run_0001 spent $0.30 and run_0002 $0.00 across one pursuit. The
    bench run's $99.99 must be invisible."""
    row = resolve("engine_cost_per_pursuit", corpus)
    assert row["value"] == 0.30
    assert row["status"] == "value"


def test_reviewer_hours_and_human_cost_are_hand_checkable(corpus):
    """90 + 30 confirmed minutes = 2.0 hours, one pursuit. At the
    synthetic pursuit_lead rate of 210.0/hr that is 420.00."""
    hours = resolve("reviewer_hours_per_proposal", corpus)
    assert hours["value"] == 2.0
    cost = resolve("human_cost_per_proposal", corpus)
    assert cost["value"] == 420.0
    blended = resolve("blended_cost_per_proposal", corpus)
    assert blended["value"] == round(420.0 + 0.30, 4)


def test_compute_vs_human_wait_splits_the_two(corpus):
    """5s compute against 120s of gate wait: 5000/125000 = 0.04. The
    bench run's 999s of compute stays out."""
    row = resolve("compute_vs_human_wait", corpus)
    assert row["value"] == 0.04


def test_gap_resolution_hours_from_the_ping_span(corpus):
    """Pinged 10:00, answered 14:00 — four hours."""
    assert resolve("gap_resolution_hours", corpus)["value"] == 4.0


def test_retry_and_cache_ratios(corpus):
    assert resolve("retry_rate", corpus)["value"] == 0.5      # 1 of 2 calls
    # cache_read 200 over input 3000
    assert resolve("cache_hit_ratio", corpus)["value"] == 0.0667


# ------------------------------------------------------ honesty contract

def test_absent_is_never_zero(corpus):
    """A metric whose source does not exist resolves absent WITH a
    reason. Rendering an unbuilt CRM feed as 0.0 would manufacture a
    failure nobody observed."""
    row = resolve("cost_bps_of_deal_value", corpus)
    assert row["status"] == "absent"
    assert row["value"] is None
    assert "CRM" in row["absent_reason"]

    baseline = resolve("cost_delta_vs_baseline", corpus)
    assert baseline["status"] == "absent"
    assert "WP-Zero" in baseline["absent_reason"]


def test_sub_min_n_rates_render_as_counts(corpus):
    """win_rate carries min_n 30 and the fixture has one decided
    pursuit: the value must not render as a percentage."""
    row = resolve("win_rate", corpus)
    assert row["status"] == "count_only"
    assert row["n"] == 1
    assert "n=1" in row["display"]
    assert row["caveat"] and "significance" in row["caveat"]


def test_estimated_and_caveat_travel_with_the_value(corpus, registry):
    """A caveat kept somewhere else is a caveat nobody reads."""
    estimated = [m for m, e in registry.items()
                 if e.get("reliability", {}).get("estimated")]
    assert estimated, "the registry flags some metrics estimated"
    for metric_id in estimated:
        assert resolve(metric_id, corpus)["estimated"] is True


def test_cost_metrics_carry_the_rate_card_version(corpus):
    row = resolve("human_cost_per_proposal", corpus)
    assert row["rate_card_version"] == "synthetic-v0", (
        "a rate change must RE-LABEL the series rather than move it")


# ------------------------------------- ACCEPTANCE: unknown metric fails

def test_view_with_unknown_metric_id_fails_check_and_eval(corpus):
    """THE acceptance clause. A view naming an id the registry lacks
    raises — in the contract test that `make check` runs, and again in
    the hook `make eval` runs."""
    with pytest.raises(UnknownMetric) as caught:
        validate_views({"bogus_view": ["not_a_real_metric"]})
    assert "not_a_real_metric" in str(caught.value)
    assert "bogus_view" in str(caught.value), "the error names the view too"

    with pytest.raises(UnknownMetric):
        resolve("not_a_real_metric", corpus)


def test_the_shipped_views_all_resolve():
    validate_views()
    for name in VIEWS:
        assert VIEWS[name], f"view {name} declares no metrics"


def test_eval_run_enforces_the_same_check(tmp_path, monkeypatch):
    """`make eval` re-runs the view check, so the clause holds in both
    gates rather than only in the test suite."""
    import engine.metrics.views as views_mod
    from engine.cli.main import main

    monkeypatch.setitem(views_mod.VIEWS, "bogus", ["not_a_real_metric"])
    code = main(["eval", "--at", "2026-08-10T12:00:00Z",
                 "--out", str(tmp_path)])
    assert code == 1


# --------------------------------- ACCEPTANCE: bench leaves aggregates

def _production_series(corpus):
    return [r for r in resolve_all(corpus) if r["status"] != "absent"]


def test_regression_bench_run_is_byte_invisible_to_production_series():
    """THE acceptance clause. The fixture carries a regression_bench run
    with deliberately huge numbers ($99.99, 999s compute, a tier-1
    block). Recomputing the whole series with and without it must be
    byte-identical."""
    with_bench = Corpus(FIXTURE_WS)
    series_with = json.dumps(_production_series(with_bench), sort_keys=True)

    stripped = Corpus(FIXTURE_WS)
    for pursuit in stripped.pursuits:
        pursuit.runs = [r for r in pursuit.runs if r["run_id"] != "run_0003"]
    series_without = json.dumps(_production_series(stripped), sort_keys=True)

    assert series_with == series_without


def test_the_bench_run_is_really_there_and_really_big():
    """Non-vacuity: if the bench run were absent or trivial, the clause
    above would pass for the wrong reason."""
    corpus = Corpus(FIXTURE_WS)
    raw = corpus.runs(production=False)
    bench = [r for r in raw if r["run_id"] == "run_0003"]
    assert bench, "the fixture must carry a regression_bench run"
    call = next(r for r in bench if r["record_type"] == "agent_call")
    assert call["cost_usd"] == 99.99
    assert call["duration_ms"] == 999000


def test_a_doctored_live_twin_does_move_the_series():
    """The other direction — proving the comparison can see a change at
    all. Relabel the bench run as live and the cost series moves."""
    corpus = Corpus(FIXTURE_WS)
    baseline = resolve("engine_cost_per_pursuit", corpus)["value"]

    doctored = Corpus(FIXTURE_WS)
    for pursuit in doctored.pursuits:
        for record in pursuit.runs:
            if (record["run_id"] == "run_0003"
                    and record["record_type"] == "run_start"):
                record["run"]["mode"] = "live"
    moved = resolve("engine_cost_per_pursuit", doctored)["value"]
    assert moved != baseline
    assert moved > baseline


# ------------------------------------------------------------ the view

def test_system_owner_view_renders_absent_lanes_with_reasons(corpus):
    payload = render_view("system_owner_weekly", corpus)
    assert payload["view"] == "system_owner_weekly"
    assert len(payload["metrics"]) == len(VIEWS["system_owner_weekly"])
    for row in payload["metrics"]:
        if row["status"] == "absent":
            assert row["absent_reason"], (
                f"{row['metric_id']} is absent without saying why")


def test_bench_view_is_separate_from_the_production_view():
    """Bench results get their own view (REPORTING_SPEC:19) — visible,
    never mixed into a production series."""
    assert set(VIEWS["bench"]).isdisjoint(set(VIEWS["system_owner_weekly"]))
