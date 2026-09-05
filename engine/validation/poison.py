"""The poison-set harness (B34(16,17)): 60 tier-labeled claims run through
the WHOLE audit path — extract, tier, verify, disposition — as one-claim
mini-sections, so a fabricated bindable fact the extractor mis-tiers is a
recorded MISS, not an invisible escape.

Caught = any Tier-1 outcome in {block, flag} (wrong-verdict-but-flagged
earns recall credit — the flag/exact split is deliberate). Recall runs
over the must_flag half; precision over everything flagged. The baseline
dual-fingerprints the PROMPTS and the CASES, both derived from what
actually ran (v1's Task-0 lesson: a guard that watches only the prompt
will compare "clean" over a moved corpus); a baseline whose fingerprints
are missing or stale REFUSES the comparison rather than printing a
misleading one. Harness runs log run.mode="regression_bench" even when
live-called — eval dollars never enter the production cost series.
"""

import json
from pathlib import Path

from engine.evals import cases as _shared
from engine.validation.validate import run_claim_audit

ROOT = Path(__file__).resolve().parents[2]
CASES_PATH = ROOT / "evals" / "poison" / "cases.json"
BASELINE_PATH = ROOT / "evals" / "poison" / "baseline.json"

_PROMPT_FILES = ("claim_auditor", "claim_verifier")

# P2-36 (P26b-3): floors are the committed counts (60 cases, 30
# must_flag); a flagged floor of one because how many the model flags is
# the measurement, not the corpus. Enforced by the re-baseline arm
# BEFORE any spend and by the lane on the recorded counts — never inside
# run_poison_suite, whose body is in the scoring-code lock (P11-C7): a
# guard edited there would stale the baseline it protects.
MINIMUM_N = {"cases": 60, "must_flag": 30, "flagged": 1}


class BaselineMismatch(RuntimeError):
    """The baseline does not describe the current prompts/cases — the
    comparison is refused, never fudged."""


def load_cases(path: Path = CASES_PATH) -> list[dict]:
    return _shared.load_cases(path)


def prompts_fingerprint() -> str:
    return _shared.files_fingerprint(
        *(ROOT / "prompts" / agent / "prompt.md" for agent in _PROMPT_FILES))


def model_fingerprint() -> str:
    return _shared.model_fingerprint(*_PROMPT_FILES)


def code_fingerprint() -> str:
    """The shared scoring roster plus this suite's own scorer (P11-C7).
    REQUIRED by check_baseline since C8."""
    return _shared.code_fingerprint(
        ("engine.validation.poison", "run_poison_suite"))


def cases_fingerprint(cases: list[dict]) -> str:
    """Derived from the cases that RAN, not from a path — the saver and
    the checker cannot compute it from different sources."""
    return _shared.object_fingerprint(cases)


def _category(case_id: str) -> str:
    return case_id.removeprefix("poison_").split("_")[0]


def run_poison_suite(store, caller, cases: list[dict], *, at: str) -> dict:
    """The suite over a live TracedCaller (whose run logs regression_bench)
    or a scripted one (metric-math proofs). Returns the report the
    baseline is written from."""
    from engine.validation import claims as _claims

    facts = _claims.fact_catalog(store)
    facts_by_id = {c["kb_id"]: c for c in facts}
    catalog_ids = frozenset(facts_by_id)

    rows = []
    for case in cases:
        claim_text = case["input"]["prompt_context"]
        capture: dict = {}
        audited, warnings = run_claim_audit(
            caller, store, section_id=case["case_id"], section_type="other",
            title=_shared.SECTION_TITLE, prose_by_slot={None: claim_text},
            labeled=claim_text, facts_by_id=facts_by_id,
            catalog_ids=catalog_ids, at=at, capture=capture)
        tier1 = [c for c in audited if c["tier"] == 1]
        caught = any(c["disposition"] in ("block", "flag") for c in tier1)
        rows.append({"case_id": case["case_id"],
                     "category": _category(case["case_id"]),
                     "must_flag": case["expected"]["must_flag"],
                     "caught": caught,
                     # P10-F16, applied here too: a single recall number
                     # could not say whether a miss was the extractor
                     # staying silent, the tier boundary, the verbatim
                     # guard discarding a correct extraction, or the
                     # verifier clearing a claim that reached it. Those
                     # are four different bugs in four different places.
                     "cause": (None if caught else _shared.miss_cause(
                         warnings=warnings, n_claims=len(audited),
                         tiers=sorted({c["tier"] for c in audited}),
                         reached_verifier=bool(tier1))),
                     "capture": capture,
                     "warnings": list(warnings)})

    flagged = [r for r in rows if r["caught"]]
    should = [r for r in rows if r["must_flag"]]
    caught_bad = [r for r in should if r["caught"]]
    recall = len(caught_bad) / len(should) if should else 1.0
    precision = (sum(1 for r in flagged if r["must_flag"]) / len(flagged)
                 if flagged else 1.0)
    confusion: dict[str, dict] = {}
    for row in rows:
        bucket = confusion.setdefault(row["category"],
                                      {"caught": 0, "total": 0})
        bucket["total"] += 1
        bucket["caught"] += int(row["caught"])
    return {
        "suite": "poison_set",
        "at": at,
        "n_cases": len(rows),
        "n_flagged": len(flagged),
        "recall": round(recall, 4),
        "precision": round(precision, 4),
        "confusion": confusion,
        "misses": sorted(r["case_id"] for r in should if not r["caught"]),
        "miss_detail": {r["case_id"]: {"category": r["category"],
                                       "cause": r["cause"],
                                       # See claim_extraction.py: the winning
                                       # cause hides any others, and an
                                       # unmarked warning is a drop reason the
                                       # taxonomy cannot name (B46).
                                       "causes_matched": _shared.matched_causes(
                                           r["warnings"]),
                                       "unmarked_warnings":
                                           _shared.unmarked_warnings(
                                               r["warnings"]),
                                       # The evidence behind the cause (C4).
                                       "output_tokens":
                                           r["capture"].get("output_tokens"),
                                       "wire_excerpt": _shared.wire_excerpt(
                                           r["capture"].get(
                                               "extraction_wire")),
                                       "warnings": r["warnings"]}
                        for r in sorted(should, key=lambda r: r["case_id"])
                        if not r["caught"]},
        "causes": _shared.cause_counts(
            [r["cause"] for r in should if not r["caught"]]),
        "prompts_fingerprint": prompts_fingerprint(),
        "cases_fingerprint": cases_fingerprint(cases),
        "model_fingerprint": model_fingerprint(),
        "code_fingerprint": code_fingerprint(),
    }


def write_baseline(report: dict, path: Path = BASELINE_PATH) -> Path:
    return _shared.write_report(report, path)


def check_baseline(path: Path = BASELINE_PATH, *,
                   cases: list[dict] | None = None) -> dict:
    """Load the baseline and REFUSE unless both fingerprints describe the
    current prompts and cases. Post-milestone prompt edits therefore fail
    here by design — a quick prompt tweak costs a live re-baseline,
    because the recorded numbers stop describing the shipped prompt."""
    if not path.exists():
        raise BaselineMismatch(f"no baseline at {path} — the poison numbers "
                               f"have not been measured yet")
    baseline = json.loads(path.read_text(encoding="utf-8"))
    for key in ("prompts_fingerprint", "cases_fingerprint",
                "model_fingerprint", "code_fingerprint"):
        if key not in baseline:
            raise BaselineMismatch(
                f"baseline lacks {key} — an unfingerprinted baseline cannot "
                f"prove what it measured; re-measure live")
    current_cases = cases if cases is not None else load_cases()
    if baseline["prompts_fingerprint"] != prompts_fingerprint():
        raise BaselineMismatch(
            "auditor/verifier prompts changed since the baseline was "
            "measured — the recorded numbers no longer describe the shipped "
            "prompt; re-measure live before trusting them")
    if baseline["cases_fingerprint"] != cases_fingerprint(current_cases):
        raise BaselineMismatch(
            "the poison cases changed since the baseline was measured — "
            "re-measure live (the corpus moved under the guard)")
    if baseline["model_fingerprint"] != model_fingerprint():
        raise BaselineMismatch(
            "the model pins or sampling parameters changed since the "
            "baseline was measured — the same prompts on the same cases at a "
            "different temperature is a different system; re-measure live")
    if baseline["code_fingerprint"] != code_fingerprint():
        raise BaselineMismatch(
            "the SCORING CODE changed since the baseline was measured — the "
            "parser, prompt builder or scorer that turned model output into "
            "this number is not the one running now, and prompts/cases/model "
            "cannot see that (P11-C7); re-measure live")
    # P2-35 (P26b-3): the measures themselves, against their sibling lock
    # — the four checks above prove the environment, this one proves the
    # number was the one recorded.
    problem = _shared.verify_lock(path, baseline)
    if problem:
        raise BaselineMismatch(problem)
    return baseline
