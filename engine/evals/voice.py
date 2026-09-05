"""Voice component suite (EVAL_SUITE Tier-1 row; B40/D24).

Deterministic by design, not by convenience: model voice judgment is A2's
Voice Miner under A4 calibration (B34(10)), so what P10 can honestly
gate is the approved prohibited-word list applied by code. That is
enough to do the job the backlog line names — the voice component eval
gates voice-spec promotion (config/voice-spec.md:7): a spec edit that
loses detection fails this lane and cannot promote silently.

The lane is spec-FINGERPRINTED, mirroring the injection suite's
drift-lock: recorded.json carries the digest of the voice spec that
produced the numbers, so editing the spec fails the comparison until a
human re-derives the record CONSCIOUSLY. That is the mechanism by which
"the owner blesses every wording change" survives them not being in the room.

Cases are planted prose per term (must flag) plus benign controls whose
near-miss words must NOT flag (a scan that fires on "Cleverage" would
train reviewers to ignore it).
"""

from pathlib import Path

from engine.evals.cases import (files_fingerprint, load_cases, rate,
                                write_report)

ROOT = Path(__file__).resolve().parents[2]
CASES_PATH = ROOT / "evals" / "voice" / "cases.json"
RECORDED_PATH = ROOT / "evals" / "voice" / "recorded.json"
VOICE_SPEC = ROOT / "config" / "voice-spec.md"

# P2-36 (P26b-3): the floor is the committed must_flag count.
MINIMUM_N = {"must_flag": 22}


def spec_fingerprint() -> str:
    """The recorded numbers are only meaningful against the spec that
    produced them — the same lock the poison baseline puts on prompts."""
    return files_fingerprint(VOICE_SPEC)


def evaluate_voice_set(path: Path = CASES_PATH) -> dict:
    """Run every case's prose through the REAL scan with the REAL
    committed term list."""
    from engine.validation.voice import prohibited_terms, voice_findings

    terms = prohibited_terms(VOICE_SPEC)
    cases = load_cases(path)
    caught = should_catch = 0
    false_positives: list[str] = []
    misses: list[str] = []
    benign_total = 0

    for case in cases:
        prose = case["input"]["prompt_context"]
        fired = bool(voice_findings("eval", prose, terms))
        if case["expected"]["must_flag"]:
            should_catch += 1
            if fired:
                caught += 1
            else:
                misses.append(case["case_id"])
        else:
            benign_total += 1
            if fired:
                false_positives.append(case["case_id"])

    return {
        "suite": "voice_scan",
        "n_cases": len(cases),
        "n_terms": len(terms),
        "n_must_flag": should_catch,
        "recall": rate(caught, should_catch, floor=MINIMUM_N["must_flag"],
                       lane="voice", of="must_flag cases"),
        "minimum_n": dict(MINIMUM_N),
        "benign_total": benign_total,
        "false_positives": sorted(false_positives),
        "misses": sorted(misses),
        "spec_fingerprint": spec_fingerprint(),
    }


def write_recorded(path: Path = RECORDED_PATH) -> Path:
    return write_report(evaluate_voice_set(), path)
