"""Intake component suite (EVAL_SUITE Tier-1 row) — and the calibration
B30(c) asked for: "the v2-local completeness target list, calibrated at
P10's eval harness."

What is measured here is the DETERMINISTIC half of intake: document
extraction, the weight parser, the date scan, and the completeness
predicate. The Intake Analyst's own extraction recall is a MODEL
measurement and is not faked — a scripted analyst would report its
script's recall, which is the same fiction B33(1) refuses for the poison
set. That half rides the live measurement lanes (A3/A4).

Two measures:
  weight_recall — hand-transcribed weight statements the parser finds
                  (goldens read from the committed twins, never produced
                  by the parser under test).
  target_coverage — the calibration B30(c) wants: which completeness
                  targets any package can actually exercise. A target no
                  corpus can fire is either dead code or an untested rule
                  (v1's rule-coverage ledger, cheap version) — naming it
                  is the point, so `dark_targets` is reported, not hidden.
"""

from pathlib import Path

from engine.evals.cases import load_cases

ROOT = Path(__file__).resolve().parents[2]
CASES_PATH = ROOT / "evals" / "intake" / "cases.json"
FIXTURES = ROOT / "tests" / "fixtures"

# Every target the completeness predicate can emit (engine/intake/brief.py
# `completeness`), transcribed from the code so a new rule with no case
# shows up as dark rather than silently unmeasured.
ALL_TARGETS = (
    "buyer.name",
    "procurement.what_is_bought",
    "procurement.response_structure",
    "requirements_matrix",
    "procurement.deadlines",
    "requirements_matrix.weight",
)


def evaluate_intake_set(path: Path = CASES_PATH) -> dict:
    """Run each case's document through the REAL extractor and weight
    parser, then exercise the completeness predicate against a brief
    skeleton carrying only what the case says the code can know."""
    from engine.intake.brief import _stated_weight_values, completeness
    from engine.intake.extract import extract

    cases = load_cases(path)
    found = expected_total = 0
    misses: list[str] = []
    fired_targets: set[str] = set()
    date_cases = date_hits = 0

    for case in cases:
        doc = extract(FIXTURES / case["input"]["files"][0])
        # P15/C3: the parser now returns one entry per OCCURRENCE (B67-F1's
        # set-dedup fix); this lane's goldens are distinct-value labels, so
        # collapse back to values for the recall join.
        stated = set(_stated_weight_values([doc]))
        golden = set(case["expected"]["labels"])
        expected_total += len(golden)
        found += len(golden & stated)
        for weight in sorted(golden - stated):
            misses.append(f"{case['case_id']}: {weight} not parsed")

        if case["input"].get("description", "").startswith("DATES"):
            date_cases += 1
            if doc.date_candidates:
                date_hits += 1

        # An empty brief makes every target fire that CAN fire for this
        # document — the coverage question, not a quality claim.
        empty = {"buyer": {}, "procurement": {}, "requirements_matrix": []}
        for miss in completeness(empty, [doc]):
            fired_targets.add(miss["target"])

    dark = [t for t in ALL_TARGETS if t not in fired_targets]
    return {
        "suite": "intake_extraction",
        "n_cases": len(cases),
        "n_packages": len({c["input"]["files"][0] for c in cases}),
        "weight_recall": (round(found / expected_total, 4)
                          if expected_total else 1.0),
        "weight_misses": sorted(misses),
        "target_coverage": round(len(fired_targets) / len(ALL_TARGETS), 4),
        "targets_fired": sorted(fired_targets),
        "dark_targets": dark,
        "date_scan_recall": (round(date_hits / date_cases, 4)
                             if date_cases else 1.0),
    }
