"""Views: the named screens, and the contract that every number on them
resolves to a real metric_id.

R6's rule — "a chart never computes a metric inline" — only holds if a
chart cannot name something the registry does not define. So a view
DECLARES its metric_ids, validate_views() resolves every one of them
against config/metrics.json, and an unknown id raises. That check runs
inside `make check` (contract test) and again inside `make eval`, which
is what "unknown metric_id fails the build" means in a repo with no CI
pipeline to fail.

P10 builds the system-owner weekly view and the bench view. The other
three audiences (pursuit_lead live, practice leadership, finance exec)
are registry-declared and land with real deployment — declaring them
here without building them would be a screen that lies about existing.
"""

from engine.metrics.resolver import (Corpus, UnknownMetric, load_registry,
                                     resolve)

# The system-owner weekly view (REPORTING_SPEC's second audience, and the
# one spec/reporting/dashboard-mockup.html renders). Ordered as the
# mockup groups them: quality first, then cost, then operations.
SYSTEM_OWNER_WEEKLY = [
    "edit_survival_rate",
    "edit_reason_mix",
    "review_rounds_to_accept",
    "reviewer_hours_per_proposal",
    "blended_cost_per_proposal",
    "engine_cost_per_pursuit",
    "engine_cost_per_section",
    "gap_resolution_hours",
    "tier1_block_rate",
    "tier1_waiver_rate",
    "compute_vs_human_wait",
    "run_success_rate",
    "injection_screen_flags",
    "anonymization_scan_result",
]

# Bench results get their own view (REPORTING_SPEC:19) — visible, but
# never mixed into a production series.
BENCH_VIEW = [
    "eval_pass_state",
    "false_gap_rate",
    "red_team_score",
]

VIEWS = {
    "system_owner_weekly": SYSTEM_OWNER_WEEKLY,
    "bench": BENCH_VIEW,
}


def validate_views(views=None, *, registry=None) -> None:
    """Raise UnknownMetric if any view names an id the registry lacks.

    This is the enforcement point for the frozen acceptance clause. It
    is deliberately a function rather than import-time work so the error
    names the view AND the id, which a bare KeyError at import would
    not."""
    registry = registry if registry is not None else load_registry()
    views = views if views is not None else VIEWS
    for view_name, metric_ids in views.items():
        for metric_id in metric_ids:
            if metric_id not in registry:
                raise UnknownMetric(
                    f"view {view_name!r} names {metric_id!r}, which is not "
                    f"in config/metrics.json — a chart naming an unknown "
                    f"metric fails the build (R6)")


def render_view(name: str, corpus: Corpus, *, registry=None) -> dict:
    """Resolve one view. Absent metrics stay in the payload carrying
    their reason: a screen that silently drops what it cannot compute
    teaches its reader that everything shown is everything there is."""
    registry = registry if registry is not None else load_registry()
    if name not in VIEWS:
        raise KeyError(f"unknown view {name!r}; known: {sorted(VIEWS)}")
    validate_views({name: VIEWS[name]}, registry=registry)
    rows = [resolve(metric_id, corpus, registry=registry)
            for metric_id in VIEWS[name]]
    return {
        "view": name,
        "metrics": rows,
        "absent_count": sum(1 for r in rows if r["status"] == "absent"),
        "count_only": [r["metric_id"] for r in rows
                       if r["status"] == "count_only"],
    }
