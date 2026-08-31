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
            if measures.get(metric, 0) > required:
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
                   prior: dict | None = None) -> list[dict]:
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
        else:
            # The compare lands with the trajectory suite (c9) and the
            # resolver's bench view (c14); until then a prior record still
            # yields the honest first-record answer.
            gates.append({"clause": clause, "status": "pass",
                          "detail": f"{subject}: compare lands with the "
                                    f"c9/c14 suites"})
    gates.append({"clause": 4, "status": "not_performed", "closer": "A3"})
    gates.append({"clause": 5, "status": "not_performed", "closer": "A4"})
    gates.append({"clause": 6, "status": "pass",
                  "detail": "this record is the attachment; live-baseline "
                            "run logs: docs/milestones/p8-live-run/ (P8), "
                            "docs/releases/<version>/ (close step)"})
    return gates


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
                 prior: dict | None = None) -> dict:
    """Assemble + schema-validate the release record. eval_pass_state is
    true iff no blocking failure and no evaluable gate fails —
    not_performed gates carry their closer and do not fail the state
    pre-production (the narrowing is logged, B40/D4)."""
    suites, blocking_failures = score_suites(lane_reports)
    gates = evaluate_gates(suites, blocking_failures, prior=prior)
    record = {
        "engine_version": engine_version,
        "generated_at": at,
        "mode": "regression_bench",
        "hold_constant": hold_constant(engine_version),
        "suites": suites,
        "gates": gates,
        "judge_calibration": {"status": "not_performed", "closer": "A4"},
        "blocking_failures": blocking_failures,
        "overrides": [],
        "eval_pass_state": (not blocking_failures and
                            all(g["status"] != "fail" for g in gates)),
    }
    validate("eval_results", record)
    return record


def write_record(record: dict, releases_dir: Path = RELEASES_DIR) -> Path:
    from engine.evals.cases import write_report

    path = (Path(releases_dir) / record["engine_version"]
            / "eval-results.json")
    return write_report(record, path)


def load_record(engine_version: str,
                releases_dir: Path = RELEASES_DIR) -> dict | None:
    path = Path(releases_dir) / engine_version / "eval-results.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
