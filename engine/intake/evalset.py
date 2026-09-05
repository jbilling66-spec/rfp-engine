"""The injection eval harness (B34(18), closes B30(c)) — beside its
subject, mirroring engine/kb/evalset.py.

Cases are NOVEL PARAPHRASES per attack family, never lexicon copies — a
suite the regexes match by construction is recall fiction. The screen is
deterministic code, so unlike the poison set these numbers are REAL when
computed offline: per-family recall over the current lexicon is recorded
in evals/injection/recorded.json and drift-tested — a lexicon edit
changes the numbers, the drift test fails, and the record is re-derived
CONSCIOUSLY. Misses are honest; the P10 bar decides what to do about
them (B33(2)). Recorded-not-blocking at P8.
"""

from pathlib import Path

from engine.evals import cases as _shared
from engine.intake.extract import ExtractedDoc
from engine.intake.screen import _PATTERNS, screen

ROOT = Path(__file__).resolve().parents[2]
CASES_PATH = ROOT / "evals" / "injection" / "cases.json"
RECORDED_PATH = ROOT / "evals" / "injection" / "recorded.json"

# P2-36 (P26b-3): floors are the committed counts — every family at
# least one case (the smallest has 5), 6 held-out attacks, 6 benign
# controls.
MINIMUM_N = {"per_family": 1, "held_out": 6, "benign": 6}


def load_cases(path: Path = CASES_PATH) -> list[dict]:
    return _shared.load_cases(path)


def lexicon_fingerprint() -> str:
    """Derived from the live pattern registry — the recorded numbers are
    only meaningful against the lexicon that produced them."""
    return _shared.object_fingerprint(_PATTERNS)


def cases_fingerprint(cases: list[dict]) -> str:
    return _shared.object_fingerprint(cases)


def evaluate_injection_set(path: Path = CASES_PATH) -> dict:
    """Run every case's text through the REAL screen. Deterministic —
    the report is reproducible from the repo alone."""
    cases = load_cases(path)
    families: dict[str, dict] = {}
    false_positives: list[str] = []
    benign_total = 0
    held_caught = held_total = 0
    for case in cases:
        doc = ExtractedDoc(file=case["case_id"], format="other",
                           text=case["input"]["prompt_context"])
        fired = bool(screen(doc))
        family = case["expected"]["labels"][0]
        if case["expected"]["must_flag"]:
            bucket = families.setdefault(family, {"caught": 0, "total": 0})
            bucket["total"] += 1
            bucket["caught"] += int(fired)
            # Held-out recall is reported SEPARATELY (B40/D9): the lexicon
            # may only be tuned against the tuning half, so this is the
            # number that says whether it generalizes rather than
            # memorizes. A rising overall recall with a flat held-out
            # recall is pattern-fitting, and the pair makes that visible.
            if case.get("held_out"):
                held_total += 1
                held_caught += int(fired)
        else:
            benign_total += 1
            if fired:
                false_positives.append(case["case_id"])
    for family, bucket in families.items():
        bucket["recall"] = _shared.rate(
            bucket["caught"], bucket["total"], floor=MINIMUM_N["per_family"],
            lane="injection", of=f"family {family!r} cases")
    total = sum(b["total"] for b in families.values())
    caught = sum(b["caught"] for b in families.values())
    _shared.require_n(benign_total, MINIMUM_N["benign"], lane="injection",
                      of="benign controls")
    return {
        "suite": "injection_set",
        "n_cases": len(cases),
        "overall_recall": _shared.rate(caught, total, floor=1,
                                       lane="injection", of="attack cases"),
        "held_out_recall": _shared.rate(
            held_caught, held_total, floor=MINIMUM_N["held_out"],
            lane="injection", of="held-out attack cases"),
        "held_out_total": held_total,
        "minimum_n": dict(MINIMUM_N),
        "families": families,
        "benign_total": benign_total,
        "false_positives": sorted(false_positives),
        "lexicon_fingerprint": lexicon_fingerprint(),
        "cases_fingerprint": cases_fingerprint(cases),
    }


def write_recorded(path: Path = RECORDED_PATH) -> Path:
    return _shared.write_report(evaluate_injection_set(), path)
