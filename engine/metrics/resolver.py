"""The metric resolver (B40/D12) — nothing in engine/ read
config/metrics.json before this.

R6: a chart never computes a metric inline. It names a metric_id, and
this layer resolves the formula, the filters, the grain, min_n, the
estimated flag and the comparability keys from the registry. That is
what keeps a screen and a gate from quietly disagreeing.

Four disciplines the registry demands and this module enforces:

* ABSENT is not zero. A metric whose source stream does not exist yet
  resolves to status "absent" carrying WHY. Reporting an unbuilt CRM
  feed as 0.0 manufactures a failure nobody observed (the v1 metric
  contract lesson, and state.py's three-state rule).
* Sub-min_n rates render as COUNTS, never percentages — "2 of 3" is
  honest where "67%" invites a decision the sample cannot support.
* The estimated flag and the confidence caveat travel WITH the value,
  because a caveat kept somewhere else is a caveat nobody reads.
* Non-production runs never enter a production series (O3), and the
  filter is applied here rather than in each resolver, so forgetting it
  is not possible one metric at a time.

Every one of the registry's entries (36 since P26a) gets a resolver function; the
bijection is test-enforced, so a new metric_id cannot land unresolvable
and a resolver cannot outlive its registry entry.
"""

import json
from pathlib import Path

from engine.metrics.walker import production_only, walk

ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = ROOT / "config" / "metrics.json"
RATES_PATH = ROOT / "config" / "rates.yaml"

# Streams with no producer in the engine yet. Named here so a resolver
# reports "absent because the source lands at A1", not a zero.
UNSOURCED_STREAMS = {
    "crm": "the CRM stream lands with real deployment (A-phase)",
    "manual_entry": "requires the WP-Zero baseline capture (A1)",
}


class UnknownMetric(KeyError):
    """A view named a metric_id the registry does not define. Raised so
    an unknown id fails the build rather than rendering as blank."""


def load_registry(path: Path = REGISTRY_PATH) -> dict[str, dict]:
    entries = json.loads(Path(path).read_text(encoding="utf-8"))
    return {entry["metric_id"]: entry for entry in entries}


def load_rates(path: Path = RATES_PATH) -> dict | None:
    if not Path(path).exists():
        return None
    import yaml
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


# --------------------------------------------------------------- context

class Corpus:
    """Everything the resolvers read, gathered once: production records
    only, plus the raw walk for bench views."""

    def __init__(self, workspace: Path):
        self.pursuits = walk(workspace)
        self.rates = load_rates()

    def runs(self, *, production=True) -> list[dict]:
        records = [r for p in self.pursuits for r in p.runs]
        return production_only(records) if production else records

    def events(self) -> list[dict]:
        return [e for p in self.pursuits for e in p.events]

    def pings(self) -> list[dict]:
        return [p for pursuit in self.pursuits for p in pursuit.pings]

    def event_kind(self, kind: str) -> list[dict]:
        return [e for e in self.events() if e.get("kind") == kind]

    def run_totals(self, *, production=True) -> list[dict]:
        return [r["run"]["totals"] for r in self.runs(production=production)
                if r.get("record_type") == "run_end"
                and "totals" in r.get("run", {})]

    def production_pursuit_ids(self) -> set[str]:
        return {r["pursuit_id"] for r in self.runs()}


# ------------------------------------------------------------- resolvers
# Each returns (value, n) or None when the metric is unmeasurable from the
# records present. None means "no denominator", which renders as absent —
# never as zero.

def _sum_totals(corpus, field) -> tuple[float, int]:
    totals = corpus.run_totals()
    return sum(t.get(field, 0) for t in totals), len(totals)


def _r_engine_cost_per_pursuit(corpus):
    ids = corpus.production_pursuit_ids()
    if not ids:
        return None
    total, _ = _sum_totals(corpus, "cost_usd")
    return round(total / len(ids), 4), len(ids)


def _r_engine_cost_per_section(corpus):
    calls = [r for r in corpus.runs()
             if r.get("record_type") == "agent_call"
             and (r.get("target") or {}).get("section_id")]
    if not calls:
        return None
    sections = {c["target"]["section_id"] for c in calls}
    return round(sum(c.get("cost_usd", 0.0) for c in calls) / len(sections), 4), \
        len(sections)


def _r_retry_rate(corpus):
    calls = [r for r in corpus.runs() if r.get("record_type") == "agent_call"]
    if not calls:
        return None
    retried = sum(1 for c in calls if c.get("retries"))
    return round(retried / len(calls), 4), len(calls)


def _r_cache_hit_ratio(corpus):
    calls = [r for r in corpus.runs() if r.get("record_type") == "agent_call"]
    reads = sum((c.get("tokens") or {}).get("cache_read", 0) for c in calls)
    inputs = sum((c.get("tokens") or {}).get("input", 0) for c in calls)
    if not inputs:
        return None
    return round(reads / inputs, 4), len(calls)


def _r_compute_vs_human_wait(corpus):
    totals = corpus.run_totals()
    compute = sum(t.get("compute_ms", 0) for t in totals)
    human = sum(t.get("human_wait_ms", 0) for t in totals)
    if compute + human == 0:
        return None
    return round(compute / (compute + human), 4), len(totals)


def _r_run_success_rate(corpus):
    ends = [r for r in corpus.runs() if r.get("record_type") == "run_end"]
    if not ends:
        return None
    ok = sum(1 for r in ends if r["run"].get("status") == "completed")
    return round(ok / len(ends), 4), len(ends)


def _r_tier1_block_rate(corpus):
    totals = corpus.run_totals()
    if not totals:
        return None
    blocked = sum(1 for t in totals if t.get("tier1_blocks", 0) > 0)
    return round(blocked / len(totals), 4), len(totals)


def _r_tier1_waiver_rate(corpus):
    lines = [r for r in corpus.runs() if r.get("record_type") == "validation"
             and r["validation"].get("claim_tier") == 1]
    blocks = [line for line in lines
              if line["validation"].get("result") in ("block", "waived")]
    if not blocks:
        return None
    waived = sum(1 for line in blocks
                 if line["validation"].get("result") == "waived")
    return round(waived / len(blocks), 4), len(blocks)


def _r_gap_resolution_hours(corpus):
    from datetime import datetime

    spans = []
    for ping in corpus.pings():
        if ping.get("pinged_at") and ping.get("answered_at"):
            start = datetime.fromisoformat(ping["pinged_at"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(ping["answered_at"].replace("Z", "+00:00"))
            spans.append((end - start).total_seconds() / 3600.0)
    if not spans:
        return None
    return round(sum(spans) / len(spans), 4), len(spans)


def _r_reviewer_hours_per_proposal(corpus):
    sessions = corpus.event_kind("review_session")
    if not sessions:
        return None
    pursuits = {s["pursuit_id"] for s in sessions}
    minutes = sum(_session_minutes(s) for s in sessions)
    return round(minutes / 60.0 / len(pursuits), 4), len(pursuits)


def _session_minutes(session: dict) -> float:
    effort = session.get("effort") or {}
    if effort.get("confirmed_minutes") is not None:
        return float(effort["confirmed_minutes"])
    return effort.get("active_ms", 0) / 60000.0


def _r_human_cost_per_proposal(corpus):
    if not corpus.rates:
        return None
    sessions = corpus.event_kind("review_session")
    if not sessions:
        return None
    roles = corpus.rates.get("roles", {})
    default = corpus.rates.get("default_role_rate", 0.0)
    pursuits = {s["pursuit_id"] for s in sessions}
    cost = sum(_session_minutes(s) / 60.0
               * roles.get(s.get("actor_role"), default) for s in sessions)
    return round(cost / len(pursuits), 4), len(pursuits)


def _r_blended_cost_per_proposal(corpus):
    human = _r_human_cost_per_proposal(corpus)
    engine = _r_engine_cost_per_pursuit(corpus)
    if human is None or engine is None:
        return None
    return round(human[0] + engine[0], 4), min(human[1], engine[1])


def _r_review_rounds_to_accept(corpus):
    accepts = corpus.event_kind("accept")
    if not accepts:
        return None
    rounds = [a.get("revision", 0) for a in accepts]
    return round(sum(rounds) / len(rounds), 4), len(accepts)


def _r_edit_reason_mix(corpus):
    edits = corpus.event_kind("edit")
    labelled = [e for e in edits if e.get("edit_reason")]
    if not labelled:
        return None
    factual = sum(1 for e in labelled if e["edit_reason"] == "factual")
    return round(factual / len(labelled), 4), len(labelled)


def _r_edit_survival_rate(corpus):
    """Derived fresh on every read from the SAME function the card writer
    stores (B40/D18) — a stored signal that disagrees with the reported
    metric is the divergence nobody notices until it has been wrong for
    months."""
    from engine.flywheel.survival import workspace_survival

    return workspace_survival(corpus)


def _r_flywheel_yield(corpus):
    """Acceptance rate, not volume (the registry is explicit): proposals
    a steward accepted over proposals raised. A learner that raises a
    hundred lessons nobody takes is not working."""
    from engine.flywheel.proposals import ProposalStore

    proposals = ProposalStore(ROOT / "kb").list()
    decided = [p for p in proposals if p.get("decided")]
    if not decided:
        return None
    accepted = sum(1 for p in decided
                   if p["decided"]["decision"] == "accepted")
    return round(accepted / len(decided), 4), len(decided)


def _r_lesson_to_draft_lag_days(corpus):
    """Whether the flywheel actually TURNS: how long from a reviewer's
    edit to the routing that acted on it. The second half of the span —
    routed lesson to a later draft citing it — needs a corpus spanning
    more than one pursuit generation and lands with real use."""
    from datetime import datetime, timezone

    def _utc(stamp: str) -> datetime:
        # A stamp without an offset is read as UTC (the events lane and
        # the server clock both stamp UTC; P1-41 made this span real).
        parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

    spans = []
    for event in corpus.events():
        routing = event.get("flywheel_routing") or {}
        if not routing.get("processed_at") or not event.get("at"):
            continue
        edited = _utc(event["at"])
        routed = _utc(routing["processed_at"])
        spans.append((routed - edited).total_seconds() / 86400.0)
    if not spans:
        return None
    return round(sum(spans) / len(spans), 4), len(spans)


def _r_win_rate(corpus):
    outcomes = _latest_outcomes(corpus)
    decided = [o for o in outcomes.values()
               if o.get("result") in ("won", "lost")]
    if not decided:
        return None
    won = sum(1 for o in decided if o["result"] == "won")
    return round(won / len(decided), 4), len(decided)


def _latest_outcomes(corpus) -> dict[str, dict]:
    """Last-wins per pursuit (D30): outcomes are append-only and a later
    line supersedes an earlier one."""
    latest: dict[str, dict] = {}
    for event in corpus.event_kind("outcome"):
        latest[event["pursuit_id"]] = event.get("outcome", {})
    return latest


def _r_kb_citation_coverage(corpus):
    from engine.kb.store import KBStore

    cited = {kb_id for r in corpus.runs()
             if r.get("record_type") == "kb_retrieval"
             for kb_id in (r["kb"].get("cards_cited") or ())}
    cards = KBStore(ROOT / "kb").list_cards()
    corpus_cards = [c for c in cards if c.get("layer") != "fact_sheet"]
    if not corpus_cards:
        return None
    return round(len(cited) / len(corpus_cards), 4), len(corpus_cards)


def _r_fact_sheet_staleness(corpus):
    from engine.kb.store import KBStore

    facts = [c for c in KBStore(ROOT / "kb").list_cards()
             if c.get("layer") == "fact_sheet"]
    if not facts:
        return None
    dated = [c for c in facts if c.get("review_due")]
    if not dated:
        return None
    latest = max(r["ts"] for r in corpus.runs()) if corpus.runs() else None
    if latest is None:
        return None
    stale = sum(1 for c in dated if str(c["review_due"]) < latest[:10])
    return round(stale / len(dated), 4), len(dated)


def _r_injection_screen_flags(corpus):
    """P1-34: FLAGS, not screens — the registry's formula counts
    `result == 'flag'`, and zero forever is the liveness signal the
    registry names; an empty corpus is absent, never 0.0."""
    lines = [r for r in corpus.runs()
             if r.get("record_type") == "validation"
             and r["validation"].get("check") == "injection_screen"]
    if not lines:
        return None
    flags = [r for r in lines if r["validation"].get("result") == "flag"]
    return float(len(flags)), len(lines)


def _r_anonymization_scan_result(corpus):
    lines = [r for r in corpus.runs()
             if r.get("record_type") == "validation"
             and r["validation"].get("check") in
             ("anonymization", "pre_export_leakage")]
    if not lines:
        return None
    clean = all(line["validation"].get("result") != "block" for line in lines)
    return (1.0 if clean else 0.0), len(lines)


def _r_red_team_score(corpus):
    scores = [r["validation"]["score"] for r in corpus.runs()
              if r.get("record_type") == "validation"
              and r["validation"].get("check") == "red_team"
              and "score" in r["validation"]]
    if not scores:
        return None
    return round(sum(scores) / len(scores), 4), len(scores)


def _r_false_gap_rate(corpus):
    # Sourced from eval_results, which the release record produces. The
    # mapper lane measures it; resolving it from pursuit records would be
    # a second implementation that could disagree.
    return None


_r_false_gap_rate.absent_reason = (  # P2-43: the honest reason, not the generic
    "sourced from the release record's mapper lane (docs/releases/), never "
    "from pursuit records — see /api/telemetry/bench")


def _r_eval_pass_state(corpus):
    return None


_r_eval_pass_state.absent_reason = (
    "sourced from the release record (docs/releases/<engine_version>/"
    "eval-results.json) — the bench view reads it there")


def _r_requirement_coverage(corpus):
    """P0-15: the share of drafted sections whose coverage check passed —
    one validation line per section (check == 'coverage', result pass|
    flag), so the grain is the SECTION: one owed slot reads like forty.
    Slot grain waits on a rule-grain validation line (schema change);
    the registry's known_failure_mode names the trigger. Absent, never
    0.0, when no coverage line exists."""
    lines = [r for r in corpus.runs()
             if r.get("record_type") == "validation"
             and r["validation"].get("check") == "coverage"]
    if not lines:
        return None
    passed = sum(1 for r in lines if r["validation"].get("result") == "pass")
    return round(passed / len(lines), 4), len(lines)


def _r_submission_volume(corpus):
    ids = corpus.production_pursuit_ids()
    if not ids:
        return None
    return float(len(ids)), len(ids)


# P2-42: `_r_cycle_time_days` used to divide engine wall_ms by pursuits —
# the registry's formula is submission_date − receipt_date over run_log
# AND crm, and crm is unsourced; the slot is honestly unsourced now.


def _unsourced(reason_key):
    def resolver(_corpus):
        return None
    resolver.absent_reason = UNSOURCED_STREAMS[reason_key]
    return resolver


def _r_extraction_fabrication_count(corpus):
    """The two-path tripwire's production reader (P12 machinery, P13/C18
    lands B51's carrier): cell-diff findings across pursuit extraction
    artifacts. ZERO is a real measurement — paired reads existed and
    nothing diverged; None means no pursuit has an extraction artifact,
    so there was nothing to disagree about. A raw count, never a rate
    (the registry is explicit)."""
    total, seen = 0, 0
    for pursuit in corpus.pursuits:
        artifact = pursuit.root / "extraction.json"
        if not artifact.exists():
            continue
        try:
            payload = json.loads(artifact.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue  # M-23: one corrupt artifact never takes down the view
        # P1-33: the writer keys two_path by FILENAME (brief.py); the
        # reader used to look for tables_diffed on the outer dict and so
        # could never fire
        for review in (payload.get("two_path") or {}).values():
            if not isinstance(review, dict) or \
                    not review.get("tables_diffed"):
                continue
            seen += 1
            total += len(review.get("findings") or [])
    if not seen:
        return None
    return total, seen


def _r_catalog_scan_cost_share(corpus):
    """Card search is CODE (B28) — no model call, no tokens — so the
    share is 0.0 BY CONSTRUCTION whenever instrumented runs exist: the
    denominator (run cost) is real, the numerator (catalog-scan token
    cost) is architectural. The metric is the trigger watch for the
    retrieval ceiling: read it beside kb_retrieval.catalog_size in
    absolute terms (the registry's own caveat). If retrieval ever gains
    a model-called scan step, this resolver is the named site to
    attribute its cost."""
    searches = [r for r in corpus.runs()
                if r.get("record_type") == "kb_retrieval"
                and r.get("kb", {}).get("step") == "card_search"]
    if not searches:
        return None
    return 0.0, len(searches)


def _r_manual_prep_hours(corpus):
    """document_prep effort per pursuit (C17's scope; N1/R3). None until
    the pilot produces sessions — the resolver exists NOW so the metric
    is measurable on day one; the data cannot be reconstructed later.
    Reviewer-confirmed minutes preferred over passive where both exist
    (the registry formula)."""
    sessions = [e for e in corpus.event_kind("review_session")
                if (e.get("effort") or {}).get("scope") == "document_prep"]
    if not sessions:
        return None
    by_pursuit: dict[str, float] = {}
    for event in sessions:
        effort = event["effort"]
        if effort.get("confirmed_minutes") is not None:
            minutes = float(effort["confirmed_minutes"])
        else:
            minutes = float(effort.get("active_ms", 0)) / 60000.0
        key = event.get("pursuit_id", "")
        by_pursuit[key] = by_pursuit.get(key, 0.0) + minutes
    hours_per_pursuit = sum(by_pursuit.values()) / 60.0 / len(by_pursuit)
    return round(hours_per_pursuit, 4), len(sessions)


RESOLVERS = {
    "edit_survival_rate": _r_edit_survival_rate,
    "edit_reason_mix": _r_edit_reason_mix,
    "review_rounds_to_accept": _r_review_rounds_to_accept,
    "tier1_block_rate": _r_tier1_block_rate,
    "tier1_waiver_rate": _r_tier1_waiver_rate,
    "false_gap_rate": _r_false_gap_rate,
    "gap_resolution_hours": _r_gap_resolution_hours,
    "red_team_score": _r_red_team_score,
    "engine_cost_per_pursuit": _r_engine_cost_per_pursuit,
    "engine_cost_per_section": _r_engine_cost_per_section,
    "reviewer_hours_per_proposal": _r_reviewer_hours_per_proposal,
    "human_cost_per_proposal": _r_human_cost_per_proposal,
    "blended_cost_per_proposal": _r_blended_cost_per_proposal,
    "cost_delta_vs_baseline": _unsourced("manual_entry"),
    "cost_bps_of_deal_value": _unsourced("crm"),
    "cost_per_win": _unsourced("crm"),
    "cycle_time_days": _unsourced("crm"),  # P2-42: receipt_date is CRM's
    "compute_vs_human_wait": _r_compute_vs_human_wait,
    "cache_hit_ratio": _r_cache_hit_ratio,
    "retry_rate": _r_retry_rate,
    "flywheel_yield": _r_flywheel_yield,
    "lesson_to_draft_lag_days": _r_lesson_to_draft_lag_days,
    "kb_citation_coverage": _r_kb_citation_coverage,
    "fact_sheet_staleness": _r_fact_sheet_staleness,
    "win_rate": _r_win_rate,
    "submission_volume": _r_submission_volume,
    "run_success_rate": _r_run_success_rate,
    "anonymization_scan_result": _r_anonymization_scan_result,
    "eval_pass_state": _r_eval_pass_state,  # P2-43: absent WITH its reason
    "requirement_coverage": _r_requirement_coverage,  # P0-15
    "injection_screen_flags": _r_injection_screen_flags,
    # P13/C18 (B51's carrier): the five §A6 extraction metrics. Two are
    # named-unresolved with reasons — the pattern the unresolved-slots
    # test enforces:
    "extraction_fabrication_count": _r_extraction_fabrication_count,
    "catalog_scan_cost_share": _r_catalog_scan_cost_share,
    "manual_prep_hours_per_pursuit": _r_manual_prep_hours,
    "extraction_table_fidelity": None,   # sourced from the gate/release
    #   record class (like eval_pass_state) — the bench measures it, not
    #   pursuit records; wiring rides A1's real-corpus rerun.
    "extraction_seconds_per_page": None,  # timing is deliberately absent
    #   from extraction artifacts (byte-identity across kill/resume,
    #   model.py) — production wall-clock instrumentation lands with
    #   A1's live runs.
}


# ---------------------------------------------------------------- resolve

def resolve(metric_id: str, corpus: Corpus, *,
            registry: dict | None = None) -> dict:
    """One metric, resolved with everything a renderer needs and nothing
    it would have to look up elsewhere."""
    registry = registry if registry is not None else load_registry()
    if metric_id not in registry:
        raise UnknownMetric(
            f"{metric_id!r} is not in config/metrics.json — a view naming "
            f"an unknown metric fails the build (R6)")
    entry = registry[metric_id]
    reliability = entry.get("reliability", {})
    min_n = reliability.get("min_n")
    out = {
        "metric_id": metric_id,
        "name": entry.get("name"),
        "unit": entry.get("unit"),
        "grain": entry.get("grain"),
        "estimated": bool(reliability.get("estimated")),
        "min_n": min_n,
        "caveat": reliability.get("confidence_caveat"),
        "status": "absent",
        "value": None,
        "n": 0,
        "absent_reason": None,
    }

    resolver = RESOLVERS.get(metric_id)
    if resolver is None:
        out["absent_reason"] = (
            "no producer yet — this metric's writer lands later in P10")
        return out

    result = resolver(corpus)
    if result is None:
        out["absent_reason"] = getattr(
            resolver, "absent_reason",
            "no records in this workspace satisfy the metric's filters")
        return out

    value, n = result
    out["value"] = value
    out["n"] = n
    if min_n is not None and n < min_n:
        # A rate over too few denominators renders as a count. "2 of 3"
        # is honest where "67%" invites a decision the sample cannot bear.
        out["status"] = "count_only"
        out["display"] = f"{value} over n={n} (min_n {min_n})"
    else:
        out["status"] = "value"
    if entry.get("family") == "cost" and corpus.rates:
        out["rate_card_version"] = corpus.rates.get("rate_card_version")
    return out


def resolve_all(corpus: Corpus, metric_ids=None, *,
                registry: dict | None = None) -> list[dict]:
    registry = registry if registry is not None else load_registry()
    ids = list(metric_ids) if metric_ids is not None else list(registry)
    return [resolve(metric_id, corpus, registry=registry)
            for metric_id in ids]
