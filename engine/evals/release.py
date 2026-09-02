"""Release gates + the record writer (B40/D4): score every lane with ONE
bar-vs-measures implementation, evaluate the six promotion clauses (E7,
pre-production reading — the closer for real environments is A5/A6),
and write the eval-results record `make eval` exits by. The record is
schema-validated at build time (a writer that can emit an invalid record
would make the contract decorative).
"""

import json
from pathlib import Path

from engine.contracts import validate

ROOT = Path(__file__).resolve().parents[2]
RELEASES_DIR = ROOT / "docs" / "releases"

# Bar keys share a closed compare vocabulary (B11: scalar bar per metric).
# family_floor: every family's recall clears the floor (min, never mean —
# the weakest family is the one an attacker uses). benign_false_positives:
# at most N cases fired wrongly. A `<name>_max` key is a CEILING on
# measures[<name>] (false_gap_rate_max: a rate you must stay under —
# the direction is in the key so a record never hides which way a bar
# points). Anything else: measures[key] >= bar[key].


def _bar_misses(bar: dict, measures: dict) -> list[str]:
    misses = []
    for key, required in bar.items():
        if key.endswith("_max"):
            metric = key[:-len("_max")]
            # P2-32: a MISSING measure fails a ceiling bar exactly as it
            # fails a floor bar — a lane that drops the key cannot clear it
            if metric not in measures or measures[metric] > required:
                misses.append(metric)
        elif key == "family_floor":
            families = measures.get("families", {})
            weakest = min((f["recall"] for f in families.values()),
                          default=0.0)
            if weakest < required:
                misses.append("family_floor")
        elif key == "benign_false_positives":
            if len(measures.get("false_positives", ())) > required:
                misses.append("benign_false_positives")
        else:
            if measures.get(key, 0.0) < required:
                misses.append(key)
    return misses


def score_suites(lane_reports: dict) -> tuple[dict, list[str]]:
    """Compute each lane's status from bar vs measures — the lane never
    grades itself. Pre-set statuses (baseline_stale, not_measured_live)
    pass through and count as blocking failures on blocking lanes: an
    unmeasured or stale blocking bar cannot promote."""
    suites: dict = {}
    blocking_failures: list[str] = []
    for name in sorted(lane_reports):
        entry = dict(lane_reports[name])
        if "status" in entry:
            # P2-33: a pre-set NON-pass status (baseline_stale,
            # not_measured_live) is the lane's own verdict; a lane that
            # pre-sets "pass" is still graded against its bars, so it can
            # never grade itself green
            if entry["status"] == "pass":
                misses = _bar_misses(entry.get("bar", {}),
                                     entry.get("measures", {}))
                if misses:
                    entry["status"] = "fail"
            else:
                misses = [entry["status"]]
        else:
            misses = _bar_misses(entry.get("bar", {}),
                                 entry.get("measures", {}))
            entry["status"] = "fail" if misses else "pass"
        if entry.get("blocking") and entry["status"] != "pass":
            blocking_failures.extend(f"{name}.{miss}" for miss in misses)
        suites[name] = entry
    return suites, blocking_failures


def evaluate_gates(suites: dict, blocking_failures: list[str], *,
                   prior: dict | None = None,
                   hold_constant: dict | None = None) -> list[dict]:
    """The six promotion clauses. Clauses a phase has not made evaluable
    carry not_performed + their closer, visibly (G-J) — never silently
    omitted. prior = the last committed release record, for the
    regression clauses; None means there is nothing to regress from."""
    gates = [
        {"clause": 1,
         "status": "fail" if blocking_failures else "pass",
         "detail": (f"unmet blocking bars: {', '.join(blocking_failures)}"
                    if blocking_failures
                    else "every blocking component bar met")},
    ]
    for clause, subject in ((2, "trajectory cost/tool-call regression"),
                            (3, "bench coverage and gap-rate")):
        if prior is None:
            gates.append({"clause": clause, "status": "pass",
                          "detail": f"no prior release record to compare "
                                    f"{subject} against (first record)"})
            continue
        gates.append(_regression_clause(clause, subject, suites, prior,
                                        hold_constant))
    gates.append({"clause": 4, "status": "not_performed", "closer": "A3"})
    gates.append({"clause": 5, "status": "not_performed", "closer": "A4"})
    gates.append({"clause": 6, "status": "pass",
                  "detail": "this record is the attachment; live-baseline "
                            "run logs: docs/milestones/p8-live-run/ (P8), "
                            "docs/releases/<version>/ (close step)"})
    return gates


# P0-9 (P26a Group E): the regression clauses compare MEASURED numbers.
# Clause 2 — trajectory cost/tool-calls per section (the CI slice's
# deterministic call pattern; more than this fraction worse fails).
# Clause 3 — bench coverage (mapper recall_at_5) not lower and gap-rate
# (mapper false_gap_rate) not higher than the prior: strict, per the
# spec's "not worse".
TRAJECTORY_REGRESSION_TOLERANCE = 0.20
_CLAUSE_MEASURES = {
    2: (("trajectory", "cost_per_section", "lower"),
        ("trajectory", "tool_calls_per_section", "lower")),
    3: (("mapper", "recall_at_5", "higher"),
        ("mapper", "false_gap_rate", "lower")),
}
# The comparability keys that ANNOTATE a compare (recorded in the
# detail) but never block it: engine_version is the axis compared
# across, and a prompt or KB change is exactly when regression matters.
_ANNOTATE_KEYS = ("config_digest", "kb_snapshot", "model_pins",
                  "prompt_version")


def _worse(direction: str, now: float, then: float, tolerance: float) -> bool:
    if direction == "lower":
        return now > then * (1 + tolerance) + 1e-12
    return now < then * (1 - tolerance) - 1e-12


def _regression_clause(clause: int, subject: str, suites: dict,
                       prior: dict, constant: dict | None) -> dict:
    tolerance = TRAJECTORY_REGRESSION_TOLERANCE if clause == 2 else 0.0
    prior_suites = prior.get("suites", {})
    drift = [k for k in _ANNOTATE_KEYS
             if constant is not None
             and prior.get("hold_constant", {}).get(k) != constant.get(k)]
    parts, failed, missing = [], [], []
    for lane, key, direction in _CLAUSE_MEASURES[clause]:
        now = (suites.get(lane) or {}).get("measures", {}).get(key)
        then = (prior_suites.get(lane) or {}).get("measures", {}).get(key)
        if not isinstance(now, (int, float)) or \
                not isinstance(then, (int, float)):
            missing.append(f"{lane}.{key}")
            continue
        worse = _worse(direction, float(now), float(then), tolerance)
        parts.append(f"{lane}.{key} {now} vs prior {then}"
                     + (" WORSE" if worse else " ok"))
        if worse:
            failed.append(f"{lane}.{key}")
    if missing and not parts:
        return {"clause": clause, "status": "not_performed",
                "detail": f"{subject}: no measure to compare — missing "
                          f"{', '.join(missing)} (prior "
                          f"{prior.get('engine_version')})",
                "closer": "the lane that emits the measure"}
    detail = (f"{subject} against {prior.get('engine_version')}: "
              + "; ".join(parts))
    if missing:
        detail += f"; not compared: {', '.join(missing)}"
    if drift:
        detail += f"; hold_constant drift noted: {', '.join(drift)}"
    return {"clause": clause, "status": "fail" if failed else "pass",
            "detail": detail}


def latest_prior(releases_dir: Path = RELEASES_DIR, *,
                 exclude_version: str | None = None) -> dict | None:
    """The most recent committed release record by generated_at — never
    by directory name (0.1.0+938df5b sorts before 0.1.0+0c8d709 and
    carries no chronology). The current version is excluded so a rerun
    never compares a record against itself."""
    best = None
    for path in Path(releases_dir).glob("*/eval-results.json"):
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("engine_version") == exclude_version:
            continue
        if record.get("mode") != "regression_bench":
            continue
        if best is None or record.get("generated_at", "") > \
                best.get("generated_at", ""):
            best = record
    return best


def hold_constant(engine_version: str) -> dict:
    """The comparability keys (R11). prompt_version is formally aliased
    to config_digest (B40/D5). rate_card_version reads config/rates.yaml
    once it exists (c13); before that the honest value is 'unset'."""
    import yaml

    from engine.kb.store import KBStore
    from engine.llm.config import MODELS_YAML, effective_config
    from engine.runlog.writer import config_digest

    digest = config_digest(effective_config())
    tiers = yaml.safe_load(MODELS_YAML.read_text(encoding="utf-8"))["tiers"]
    rates_path = ROOT / "config" / "rates.yaml"
    rate_card = "unset"
    if rates_path.exists():
        rate_card = yaml.safe_load(
            rates_path.read_text(encoding="utf-8")).get(
                "rate_card_version", "unset")
    return {"engine_version": engine_version,
            "config_digest": digest,
            "kb_snapshot": KBStore(ROOT / "kb").snapshot(),
            "model_pins": {tier: entry["model"]
                           for tier, entry in sorted(tiers.items())},
            "prompt_version": digest,
            "judge_model": None,
            "rate_card_version": rate_card}


def build_record(lane_reports: dict, *, engine_version: str, at: str,
                 prior: dict | None = None,
                 overrides: list[dict] | None = None) -> dict:
    """Assemble + schema-validate the release record. eval_pass_state is
    true iff no blocking failure and no evaluable gate fails without a
    named owner's written override (clauses 2–4 only, the spec's rule) —
    not_performed gates carry their closer and do not fail the state
    pre-production (the narrowing is logged, B40/D4)."""
    suites, blocking_failures = score_suites(lane_reports)
    constant = hold_constant(engine_version)
    gates = evaluate_gates(suites, blocking_failures, prior=prior,
                           hold_constant=constant)
    overrides = list(overrides or [])
    overridden = {o["gate_clause"] for o in overrides}
    failing = [g["clause"] for g in gates if g["status"] == "fail"]
    unresolved = [c for c in failing if c not in overridden]
    record = {
        "engine_version": engine_version,
        "generated_at": at,
        "mode": "regression_bench",
        "hold_constant": constant,
        "suites": suites,
        "gates": gates,
        "judge_calibration": {"status": "not_performed", "closer": "A4"},
        "blocking_failures": blocking_failures,
        "overrides": overrides,
        "eval_pass_state": not blocking_failures and not unresolved,
    }
    validate("eval_results", record)
    return record


def write_record(record: dict, releases_dir: Path = RELEASES_DIR) -> Path:
    """P2-34: a record is never clobbered — an existing one moves to
    history/<generated_at>.json beside it first (the rebaseline
    discipline, applied to release records)."""
    from engine.evals.cases import write_report

    path = (Path(releases_dir) / record["engine_version"]
            / "eval-results.json")
    if path.exists():
        prior = json.loads(path.read_text(encoding="utf-8"))
        stamp = str(prior.get("generated_at", "undated")).replace(":", "")
        archive = path.parent / "history" / f"{stamp}.json"
        if not archive.exists():
            write_report(prior, archive)
    return write_report(record, path)


def load_record(engine_version: str,
                releases_dir: Path = RELEASES_DIR) -> dict | None:
    path = Path(releases_dir) / engine_version / "eval-results.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
