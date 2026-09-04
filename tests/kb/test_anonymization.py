"""Anonymization: the acceptance clause 'zero planted identifiers
retrievable' plus the unit behavior of the substitution/scan asymmetry.

The scan is stricter than substitution on purpose — possessives, wrapped
names, distinctive tokens, and fee restatements are where recall == 1.00
dies (E4). The result is boolean, never a rate (R13).
"""

import json
import math
from pathlib import Path

from engine.contracts import validate
from engine.kb.anonymize import apply_placeholders, scan, scan_passed
from engine.kb.evalset import (default_script, evaluate_anonymization_set,
                               retrievable_text)
from engine.runlog import read_run

from tests.kb.fixtures.corpus import PLANTED, ingest_corpus

CASES_PATH = Path(__file__).resolve().parents[2] / "evals" / "anonymization" / "cases.json"


def _retrievable_text(store) -> str:
    # M-27: the same reach as the eval harness — cards, L1 models,
    # proposals — never narrower than the lane the release gates on.
    return "\n".join(retrievable_text(store).values())


def test_planted_identifiers_absent_from_all_retrievable_text(tmp_path):
    store, reports = ingest_corpus(tmp_path / "kb")
    assert all(r.status == "ingested" for r in reports)
    text = " ".join(_retrievable_text(store).split()).lower()
    for doc_id, identifiers in PLANTED.items():
        for identifier in identifiers:
            assert identifier.lower() not in text, (
                f"{doc_id}: planted identifier {identifier!r} is retrievable"
            )
    # Distinctive fragments must be gone too, not just exact strings.
    for fragment in ("meridian", "cascade", "harborlight", "bluegrass",
                     "tallgrass", "whitfield", "raghavan", "ellison",
                     "camacho", "tuck", "1,975,000", "2,340,000"):
        assert fragment not in text, f"fragment {fragment!r} is retrievable"


def test_validation_record_emitted_per_ingested_doc(tmp_path):
    store, reports = ingest_corpus(tmp_path / "kb")
    records = read_run(store.root / "runs" / "run_0001" / "run.jsonl")
    passes = [
        r for r in records
        if r["record_type"] == "validation"
        and r["validation"] == {"check": "anonymization", "result": "pass"}
    ]
    assert len(passes) == len([r for r in reports if r.status == "ingested"])


# -- unit behavior of the substitution/scan pair ---------------------------


def test_substitution_handles_wrapped_and_possessive_forms():
    identifiers = {"Meridian Health Partners": "CLIENT"}
    wrapped = "We worked with Meridian\n   Health Partners on payroll."
    assert "[CLIENT]" in apply_placeholders(wrapped, identifiers)
    possessive = "Meridian Health Partners' cutover ran clean."
    assert apply_placeholders(possessive, identifiers).startswith("[CLIENT]'")


def test_substitution_is_longest_first():
    identifiers = {"Dana Whitfield": "REFERENCE_NAME", "Dana": "REFERENCE_NAME"}
    out = apply_placeholders("Contact Dana Whitfield directly.", identifiers)
    assert out == "Contact [REFERENCE_NAME] directly."


def test_scan_catches_what_substitution_missed():
    findings = scan(
        {"card:body": "Meridian's team praised the cutover."},
        ["Meridian Health Partners"],
    )
    assert findings and findings[0].matched == "Meridian"
    assert scan_passed(findings) is False


def test_scan_catches_fee_restatements():
    for restated in ("about $1.975M all-in", "roughly 1.975 million dollars",
                     "a total of 1975000"):
        findings = scan({"card:body": restated}, ["$1,975,000"])
        assert findings, f"fee restatement {restated!r} escaped the scan"


def test_scan_ignores_generic_tokens_alone():
    findings = scan(
        {"card:body": "A regional health system in a river valley."},
        ["Meridian Health Partners", "Cascade Valley Medical Center"],
    )
    assert scan_passed(findings) is True


def test_scan_result_is_boolean(tmp_path):
    result = scan_passed([])
    assert result is True and isinstance(result, bool)


def test_scan_flags_contact_info_unconditionally():
    findings = scan({"card:body": "Reach us at ops.lead@example-firm.example"}, [])
    assert findings and findings[0].identifier == "<contact_info>"
    findings = scan({"card:body": "Call (555) 214-8890 during hypercare."}, [])
    assert findings
    # Metrics and dates must NOT trip the phone pattern (v1: a false
    # positive trains reviewers to ignore the finding).
    clean = scan({"card:body": "3,800 employees; go-live 2026-07-31; 0.35 rate;"
                               " reconciled $1,975,000 to the penny."},
                 [])
    assert clean == []


# -- the 20-doc eval set (E4: recall == 1.00, hard block) ------------------


def test_anonymization_code_postpass_recall_true_over_eval_set(tmp_path):
    """Offline, the scripted extractor reads the planted answer key, so this
    measures the CODE POST-PASS only — the live model's own extraction recall
    is first measured with this same harness at P8's RFP_LIVE run (B30 rename:
    the old name claimed recall the offline harness cannot measure)."""
    result, failures = evaluate_anonymization_set(CASES_PATH, tmp_path)
    assert failures == []
    assert result is True and isinstance(result, bool)


def test_harness_catches_a_leak_in_the_canonical_model_only(tmp_path):
    """M-27 (P26b-2): an identifier that survives into an L1 model
    element but into no card was invisible to the harness. Plant one
    after a clean ingest of the first case and run the harness's own
    scan over the store: the failure names the canonical source."""
    from engine.kb import KBStore

    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    case = next(c for c in cases if not c["input"].get("generator"))
    ok, failures = evaluate_anonymization_set(CASES_PATH, tmp_path)
    assert ok and failures == []
    store = KBStore(tmp_path / case["case_id"] / "kb")
    model_path = next((store.root / "canonical").glob("*.json"))
    model = json.loads(model_path.read_text(encoding="utf-8"))
    needle = case["expected"]["labels"][0]
    model["elements"][0]["text"] += f" {needle}"
    model_path.write_text(json.dumps(model), encoding="utf-8")
    text = retrievable_text(store)
    assert needle.lower() not in text["card"]
    assert needle.lower() in text["canonical"]


def test_eval_cases_validate_and_held_out_quota():
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    assert len(cases) == 22  # 20 text (P2) + 2 runtime-built media (C11)
    for case in cases:
        validate("eval_case", case)
        assert case["suite"] == "anonymization_set"
        assert case["scoring"] == {"method": "assertion",
                                   "metric": "anonymization_recall",
                                   "bar": 1.0, "blocking": True}
    held_out = sum(1 for c in cases if c.get("held_out"))
    assert held_out >= math.ceil(len(cases) * 0.2)


def test_media_leak_caught_by_eval_not_scan(tmp_path, monkeypatch):
    """A reader that stops reporting media facts leaks a logo/signature
    image past every text control — the media cases are the eval-side
    control that catches it (C11's can-fail twin: proves the must_flag
    assertion is load-bearing, not decorative)."""
    import engine.kb.evalset as evalset_mod

    honest = evalset_mod.read_source

    def media_blind(path):
        source = honest(path)
        source.media = {"images": 0}
        return source

    monkeypatch.setattr(evalset_mod, "read_source", media_blind)
    result, failures = evaluate_anonymization_set(CASES_PATH, tmp_path)
    assert result is False
    assert any("anon_021" in f and "media" in f for f in failures)
    assert any("anon_022" in f and "media" in f for f in failures)


def test_sabotaged_extraction_caught_by_eval_not_code_scan(tmp_path):
    """A model that stops reporting fees leaks them past the code scan (the
    scan only knows indexed identifiers) — the labeled eval set is the
    control that still catches it. This asymmetry is why the suite exists."""
    def fee_dropping_factory(meta):
        honest = default_script(meta)["ingestion_agent"]

        def drops_fees(prompt: str) -> str:
            wire = json.loads(honest(prompt))
            wire["identifiers"] = [
                i for i in wire["identifiers"] if i["type"] != "FEE"
            ]
            return json.dumps(wire)

        return {"ingestion_agent": drops_fees}

    result, failures = evaluate_anonymization_set(
        CASES_PATH, tmp_path, script_factory=fee_dropping_factory)
    assert result is False
    assert any("anon_001" in f and "$1,240,000" in f for f in failures)
