"""Consistency, drafter and red-team lanes (c8) — the EVAL_SUITE rows
whose measurement is genuinely a MODEL judgement.

These are declared honestly rather than measured falsely. Contradiction
detection, the drafter's rubric score and the red-team's pairwise
accuracy all depend on what a model concludes; under a scripted caller
each reports its script's answer, which is the fiction B33(1) refuses
for the poison set. Each lane therefore ships its cases and its scoring
math and declares `not_measured_live` until a live measurement exists.

The consistency checker has two halves and they are measured
differently. Its CODE half — a cross-reference pointing at a slot that
never drafted, a dangling promise in the buyer's own numbering — is
deterministic and is measured here for real. Its MODEL half is the
20-case contradiction set (B34(8)), carried as data and scored live.
Splitting them is the point: a single "detection rate" spanning both
would let a code regression hide behind a model number nobody measured.
"""

from pathlib import Path

from engine.evals.cases import load_cases, rate

ROOT = Path(__file__).resolve().parents[2]
CASES_PATH = ROOT / "evals" / "consistency" / "cases.json"


# The code half's cases are SHAPES, not labelled text, so they live here
# rather than in cases.json — the eval-case contract carries prompt text
# and labels, and encoding a section/slot structure into a prompt string
# would be a fixture pretending to be data. Same reasoning as the
# trajectory suite's planted record lists.
CROSS_REF_CASES = [
    {"case_id": "consistency_code_001", "must_flag": True,
     "why": "an answer points at ref 4.2, whose slot was never drafted — "
            "a dangling promise in the buyer's own numbering",
     "sections": [
         {"ref_id": "4.1", "cross_refs": ["4.2"], "status": "drafted"},
         {"ref_id": "4.2", "status": "omitted"},
     ]},
    {"case_id": "consistency_code_002", "must_flag": True,
     "why": "the referenced ref does not exist at all",
     "sections": [
         {"ref_id": "5.1", "cross_refs": ["9.9"], "status": "drafted"},
     ]},
    {"case_id": "consistency_code_003", "must_flag": False,
     "why": "CONTROL: the reference resolves to a drafted slot",
     "sections": [
         {"ref_id": "6.1", "cross_refs": ["6.2"], "status": "drafted"},
         {"ref_id": "6.2", "status": "drafted"},
     ]},
    {"case_id": "consistency_code_004", "must_flag": False,
     "why": "CONTROL: a gated-skipped target is a decided absence, not a "
            "dangling one",
     "sections": [
         {"ref_id": "7.1", "cross_refs": ["7.2"], "status": "drafted"},
         {"ref_id": "7.2", "status": "gated_skipped"},
     ]},
    {"case_id": "consistency_code_005", "must_flag": False,
     "why": "CONTROL: no cross-references at all",
     "sections": [{"ref_id": "8.1", "status": "drafted"}]},
]


# P2-36 (P26b-3): the floor is the committed code-detectable count.
MINIMUM_N = {"code_detectable": 5}


def _drafted_from(case: dict):
    """Build the drafted shape the cross-section check reads, from the
    case's own declaration. Hand-built rather than run through drafting:
    the unit under test is the check, not the pipeline feeding it."""
    sections, slots_by_id = [], {}
    for index, spec in enumerate(case["sections"], start=1):
        slot_id = f"slot_{index}"
        slots_by_id[slot_id] = {
            "slot_id": slot_id,
            "ref_id": spec.get("ref_id"),
            "cross_refs": spec.get("cross_refs", []),
            "response_shape": "prose",
            "question_text": "q",
        }
        sections.append({
            "section_id": f"s{index}",
            "title": spec.get("title", f"Section {index}"),
            "answers": [{"slot_id": slot_id,
                         "status": spec.get("status", "drafted"),
                         "prose": spec.get("prose", ""), "kb_ids": []}],
        })
    return sections, slots_by_id


def evaluate_consistency_set(path: Path = CASES_PATH) -> dict:
    """Measure the code half; count the model half without scoring it."""
    from engine.validation import checks

    model_cases = load_cases(path)

    caught, misses = 0, []
    for case in CROSS_REF_CASES:
        drafted, slots_by_id = _drafted_from(case)
        fired = bool(checks.cross_ref_findings(drafted, slots_by_id))
        if fired == case["must_flag"]:
            caught += 1
        else:
            misses.append(case["case_id"])
    code_cases = CROSS_REF_CASES

    return {
        "suite": "consistency_set",
        "n_cases": len(model_cases) + len(code_cases),
        "n_code_detectable": len(code_cases),
        "n_model_only": len(model_cases),
        "code_detection_rate": rate(caught, len(code_cases),
                                    floor=MINIMUM_N["code_detectable"],
                                    lane="consistency",
                                    of="code-detectable cases"),
        "minimum_n": dict(MINIMUM_N),
        "misses": sorted(misses),
    }
