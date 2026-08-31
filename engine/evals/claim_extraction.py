"""The CLAIM-extraction recall suite (F6) — the component gap the P8 live
milestone named.

Named `claim_extraction`, not `extraction`, since B44/B46: WP12 introduces
a document extraction layer (parsing PDFs and DOCX into a canonical
model), and "extraction" would then name two unrelated subsystems. This
one measures whether the claim auditor pulls a bindable claim OUT OF
PROSE. Nothing here parses a document. The distinction is not pedantry —
P10-F16 was a two-phase misattribution that happened because a number's
name did not match the subsystem it described.

All four poison-set misses were ONE failure mode: the auditor never
EXTRACTED the poisoned claim as Tier-1, so it never reached the verifier
(which had zero misses on claims it did see). The poison set scores the
whole audit path and therefore cannot separate "the verifier was fooled"
from "the claim never arrived". This suite isolates the first step.
NOTE (B46): that P8 conclusion rests on a measurement that could not
distinguish four causes, and P11's diagnostic run is what tests it.

Sited as its own suite, deliberately (B40/D7): the poison baseline
dual-fingerprints its CASES, so adding extraction cases to
evals/poison/cases.json would stale that baseline and force a live
re-measure every time the set grows. Separate files, separate baselines,
one shared prompt — which is why hardening the auditor stales BOTH and
both re-measure in the single gated close commit.

Basis is live_baseline for the same reason the poison set is: under a
scripted caller the extractor returns whatever the script says, so a
FakeCaller "recall" would be the script's recall, not the model's
(B33(1)). Until the close step measures it, the honest status is
not_measured_live — never a number nobody observed.
"""

import json
from pathlib import Path

from engine.evals import cases as _shared

ROOT = Path(__file__).resolve().parents[2]
CASES_PATH = ROOT / "evals" / "claim-extraction" / "cases.json"
BASELINE_PATH = ROOT / "evals" / "claim-extraction" / "baseline.json"

_PROMPT_FILES = ("claim_auditor",)


class BaselineMismatch(RuntimeError):
    """The baseline no longer describes the current prompt/cases — the
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

    REQUIRED by check_baseline since C8. Enforcement waited for the
    diagnostic run because adding a key to the required set stales every
    existing baseline, and only a live run can refresh one."""
    return _shared.code_fingerprint(
        ("engine.evals.claim_extraction", "run_extraction_suite"))


def cases_fingerprint(cases: list[dict]) -> str:
    return _shared.object_fingerprint(cases)


def _mode(case_id: str) -> str:
    return case_id.removeprefix("extract_").rsplit("_", 1)[0]


def run_extraction_suite(store, caller, cases: list[dict], *, at: str) -> dict:
    """Run each case's prose through the REAL audit path and ask only the
    first question: did a Tier-1 claim come out?

    Scoring is deliberately blind to the verdict. A claim extracted and
    tiered correctly counts even if the verifier then clears it — this
    suite measures arrival, and conflating the two is what hid the P8
    misses inside a single recall number."""
    from engine.validation import claims as _claims
    from engine.validation.validate import run_claim_audit

    facts = _claims.fact_catalog(store)
    facts_by_id = {c["kb_id"]: c for c in facts}
    catalog_ids = frozenset(facts_by_id)

    rows = []
    for case in cases:
        prose = case["input"]["prompt_context"]
        capture: dict = {}
        audited, warnings = run_claim_audit(
            caller, store, section_id=case["case_id"], section_type="other",
            title=_shared.SECTION_TITLE, prose_by_slot={None: prose},
            labeled=prose, facts_by_id=facts_by_id,
            catalog_ids=catalog_ids, at=at, capture=capture)
        extracted_tier1 = any(c["tier"] == 1 for c in audited)
        rows.append({
            "case_id": case["case_id"],
            "capture": capture,
            "mode": _mode(case["case_id"]),
            "should_extract": case["expected"]["must_flag"],
            "extracted_tier1": extracted_tier1,
            # A miss has several very different causes and one number
            # cannot tell them apart. The extractor may have stayed
            # silent (a breadth problem); it may have tiered the claim
            # down (a boundary problem — the opposite prompt edit); or
            # the claim may have been extracted and then DROPPED by the
            # verbatim guard in parse_extraction_wire, which rejects any
            # text that is not literally present in the prose.
            #
            # That third cause is the one that hid. run_claim_audit
            # reports every drop, and this suite used to discard those
            # warnings — so a paraphrased-but-correct extraction scored
            # identically to a model that said nothing, and the recorded
            # verdict ("never extracted") named the wrong subsystem.
            # cX cycle 2 found five misses whose calls each returned ~110
            # output tokens, against 38 for a genuinely empty answer.
            "tiers": sorted({c["tier"] for c in audited}),
            "n_claims": len(audited),
            "warnings": list(warnings),
        })

    should = [r for r in rows if r["should_extract"]]
    caught = [r for r in should if r["extracted_tier1"]]
    controls = [r for r in rows if not r["should_extract"]]
    over = [r for r in controls if r["extracted_tier1"]]

    by_mode: dict[str, dict] = {}
    for row in should:
        bucket = by_mode.setdefault(row["mode"], {"caught": 0, "total": 0})
        bucket["total"] += 1
        bucket["caught"] += int(row["extracted_tier1"])
    for bucket in by_mode.values():
        bucket["recall"] = round(bucket["caught"] / bucket["total"], 4)

    return {
        # The claim_* forms at last (B46's vocabulary split, completed
        # B50): the rename waited for a funded re-measure because
        # cases_fingerprint hashes the case OBJECTS and these keys land
        # in a measured baseline — C8 was the intended closer and missed
        # it; the B48/B49 harness-frame re-measure is the trigger the
        # re-deferral named, so it rides here.
        "suite": "claim_extraction_set",
        "at": at,
        "n_cases": len(rows),
        "claim_extraction_recall": (round(len(caught) / len(should), 4)
                                    if should else 1.0),
        "claim_over_extraction_rate": (round(len(over) / len(controls), 4)
                                       if controls else 0.0),
        "n_controls": len(controls),
        "by_mode": by_mode,
        "misses": sorted(r["case_id"] for r in should
                         if not r["extracted_tier1"]),
        "miss_detail": {
            r["case_id"]: {"tiers_extracted": r["tiers"],
                           "n_claims": r["n_claims"],
                           "cause": _shared.miss_cause(
                               warnings=r["warnings"],
                               n_claims=r["n_claims"],
                               tiers=r["tiers"]),
                           # The winning cause is one of possibly several;
                           # `causes_matched` keeps the rest, and
                           # `unmarked_warnings` is the tripwire for a drop
                           # reason the taxonomy cannot name (B46).
                           "causes_matched": _shared.matched_causes(
                               r["warnings"]),
                           "unmarked_warnings": _shared.unmarked_warnings(
                               r["warnings"]),
                           # The evidence behind the cause (C4). Without
                           # these two, `not_extracted` cannot be told from
                           # "answered and code discarded it" after the
                           # fact, and the funded run is unrepeatable.
                           "output_tokens": r["capture"].get("output_tokens"),
                           "wire_excerpt": _shared.wire_excerpt(
                               r["capture"].get("extraction_wire")),
                           "warnings": r["warnings"]}
            for r in sorted(should, key=lambda r: r["case_id"])
            if not r["extracted_tier1"]},
        "causes": _shared.cause_counts(
            [_shared.miss_cause(warnings=r["warnings"],
                                n_claims=r["n_claims"], tiers=r["tiers"])
             for r in should if not r["extracted_tier1"]]),
        "over_extracted": sorted(r["case_id"] for r in over),
        "prompts_fingerprint": prompts_fingerprint(),
        "cases_fingerprint": cases_fingerprint(cases),
        "model_fingerprint": model_fingerprint(),
        "code_fingerprint": code_fingerprint(),
    }


def write_baseline(report: dict, path: Path = BASELINE_PATH) -> Path:
    return _shared.write_report(report, path)


def check_baseline(path: Path = BASELINE_PATH, *,
                   cases: list[dict] | None = None) -> dict:
    """Same refusal discipline as the poison baseline: a baseline that
    does not describe the current prompt and cases is not a comparison,
    it is a guess wearing a number."""
    path = Path(path)
    if not path.exists():
        raise BaselineMismatch(
            f"no baseline at {path} — extraction recall has not been "
            f"measured live yet (F6 lands at the gated close step)")
    baseline = json.loads(path.read_text(encoding="utf-8"))
    for key in ("prompts_fingerprint", "cases_fingerprint",
                "model_fingerprint", "code_fingerprint"):
        if key not in baseline:
            raise BaselineMismatch(
                f"baseline lacks {key} — an unfingerprinted baseline "
                f"cannot prove what it measured; re-measure live")
    current = cases if cases is not None else load_cases()
    if baseline["prompts_fingerprint"] != prompts_fingerprint():
        raise BaselineMismatch(
            "the claim_auditor prompt changed since the baseline was "
            "measured — the recorded numbers no longer describe the "
            "shipped prompt; re-measure live")
    if baseline["cases_fingerprint"] != cases_fingerprint(current):
        raise BaselineMismatch(
            "the extraction cases changed since the baseline was measured "
            "— re-measure live (the set moved under the guard)")
    if baseline["model_fingerprint"] != model_fingerprint():
        raise BaselineMismatch(
            "the model pins or sampling parameters changed since the "
            "baseline was measured — the same prompt on the same cases at a "
            "different temperature is a different system; re-measure live")
    if baseline["code_fingerprint"] != code_fingerprint():
        raise BaselineMismatch(
            "the SCORING CODE changed since the baseline was measured — the "
            "parser, prompt builder or scorer that turned model output into "
            "this number is not the one running now, and prompts/cases/model "
            "cannot see that (P11-C7); re-measure live")
    return baseline
