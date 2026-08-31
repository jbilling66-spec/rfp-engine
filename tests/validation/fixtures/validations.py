"""Validation-stage harness (P8): chains the P7 drafting package, then
runs the REAL run_validation as run_0006 with derive-from-prompt scripts
for all five agents (the house pattern: fixture, prompt, and script
cannot drift because the script reads back what the stage composed).

The verifier fake is an honest word-overlap rule over the claim and card
body it finds in its own prompt — SUPPORTED when the claim's content
words are substantially licensed by the card, UNSUPPORTED otherwise. The
gapcase chain's answered-gap steering text (ANSWERED_TEXT, a SOC 2
sentence) therefore verifies SUPPORTED against fact kb_fact000001 with no
hand-wiring. Misbehaviours are plantable kwargs on the same factory.
"""

import hashlib
import json
import re
from pathlib import Path

from engine.kb import KBStore
from engine.llm import FakeCaller, TracedCaller, effective_config
from engine.runlog import RunLogger
from engine.validation import run_validation
from engine.validation.validate import ANCHORS_DEFAULT
from engine.version import engine_version
from tests.drafting.fixtures.drafts import (
    drafting_extras,
    run_drafting_package,
)

AT = "2026-08-07T12:00:00"  # the injected clock — hand constant, no wall time

SOC2_FACT = "kb_fact000001"
COUNT_FACT = "kb_fact000007"   # "14 certified ERP consultants on staff."
LAPSED_FACT = "kb_fact000036"  # review_due 2025-11-01 — lapsed by design

_SLOT_BLOCK = re.compile(
    r"SLOT (\S+) \| ref (\S+):\n(.*?)(?=\n\nSLOT |\n\nFACT SHEET CATALOG)",
    re.S)
_PROSE_BLOCK = re.compile(
    r"DRAFTED PROSE \(extract claims from this text only\):\n(.*?)"
    r"\n\nFACT SHEET CATALOG", re.S)
_CLAIM_LINE = re.compile(r"^CLAIM: (.+)$", re.M)
_CARD_LINE = re.compile(r"^EVIDENCE CARD (\S+) ", re.M)
_CARD_BODY = re.compile(r"\):\n(.*?)\n\nReturn JSON", re.S)
_SECTION_LINE = re.compile(r"^SECTION (\S+): ", re.M)
_SUBQ_LINE = re.compile(r"^\d+\. ", re.M)


def validation_extras(store, *, voice_path=None,
                      anchors_path=ANCHORS_DEFAULT) -> dict:
    """Drafting extras + the validation config extra (B34(27)): the fact
    sheet, rubric id, and anchors are run variables — two validation runs
    are comparable only when all three digests match."""
    from engine.validation import claims as _claims
    facts = _claims.fact_catalog(store)
    fact_digest = hashlib.sha256(json.dumps(
        [(c["kb_id"], c["summary"], c["verified_date"], c.get("review_due"))
         for c in facts], sort_keys=True).encode("utf-8")).hexdigest()
    extras = drafting_extras(voice_path)
    extras["validation"] = {
        "fact_sheet_sha256": fact_digest,
        "red_team_rubric": "rt_v1",
        "anchors_sha256": hashlib.sha256(
            Path(anchors_path).read_bytes()).hexdigest(),
    }
    return extras


def _first_sentence(prose: str) -> str:
    head = prose.strip().split(". ")[0].strip()
    return head if head.endswith(".") else head + "."


def _content_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9-]+", text.lower()) if len(w) > 2}


def make_validation_script(*, plant_unsupported=False, plant_stale=False,
                           plant_hallucinated=False, plant_contradiction=False,
                           plant_weak=False, plant_unaddressed=False,
                           fail_on_section=None):
    """One factory, plantable misbehaviours (house pattern). All five
    agents derive their wires from the prompt they were given."""

    def auditor(prompt: str) -> str:
        block = _PROSE_BLOCK.search(prompt)
        text = block.group(1) if block else prompt
        slots = _SLOT_BLOCK.findall(text + "\n\nFACT SHEET CATALOG")
        if fail_on_section is not None \
                and f"Section: {fail_on_section}" in prompt:
            raise RuntimeError("scripted validation death (fixture)")
        rows = []
        if not slots:  # Path B: whole-section prose
            slots = [(None, None, text)]
        soc2_claimed = False
        for index, (slot_id, _ref, prose) in enumerate(slots):
            first = _first_sentence(prose)
            soc2 = re.search(r"We hold a current SOC 2 Type II[^.]*\.", prose)
            if soc2 and not soc2_claimed:
                soc2_claimed = True
                rows.append({"slot_id": slot_id, "text": soc2.group(0),
                             "tier": 1, "fact_sheet_ref": SOC2_FACT})
            elif plant_unsupported and index == 0:
                rows.append({"slot_id": slot_id, "text": first, "tier": 1,
                             "fact_sheet_ref": COUNT_FACT})
            elif plant_stale and index == 0:
                rows.append({"slot_id": slot_id, "text": first, "tier": 1,
                             "fact_sheet_ref": LAPSED_FACT})
            else:
                rows.append({"slot_id": slot_id, "text": first, "tier": 2,
                             "fact_sheet_ref": None})
        if plant_hallucinated:
            rows.append({"slot_id": slots[0][0],
                         "text": "We guarantee quantum teleportation of "
                                 "payroll records.",
                         "tier": 1, "fact_sheet_ref": None})
        return json.dumps({"claims": rows})

    def verifier(prompt: str) -> str:
        claim = _CLAIM_LINE.search(prompt).group(1)
        card_id = _CARD_LINE.search(prompt).group(1)
        body = _CARD_BODY.search(prompt).group(1)
        if plant_stale and card_id == LAPSED_FACT:
            return json.dumps({"verdict": "SUPPORTED",
                               "reasons": ["scripted: lapsed-card support"]})
        words = _content_words(claim)
        overlap = len(words & _content_words(body)) / max(1, len(words))
        verdict = "SUPPORTED" if overlap >= 0.6 else "UNSUPPORTED"
        return json.dumps({"verdict": verdict,
                           "reasons": [f"overlap {overlap:.2f}"]})

    def compliance(prompt: str) -> str:
        n = len(_SUBQ_LINE.findall(prompt.split("ANSWER PROSE:")[0]))
        rows = [{"index": i, "addressed": True} for i in range(n)]
        if plant_unaddressed and rows:
            rows[-1]["addressed"] = False
        return json.dumps({"addressed": rows})

    def consistency(prompt: str) -> str:
        ids = _SECTION_LINE.findall(prompt)
        if plant_contradiction and len(ids) >= 2:
            return json.dumps({"contradictions": [
                {"section_ids": ids[:2],
                 "detail": "scripted contradiction between the first two"}]})
        return json.dumps({"contradictions": []})

    def red_team(prompt: str) -> str:
        ids = _SECTION_LINE.findall(prompt.split("THE DRAFT:")[-1])
        sections = [{"section_id": s, "score": 8, "weaknesses": []}
                    for s in ids]
        if plant_weak and sections:
            sections[-1]["score"] = 3
            sections[-1]["weaknesses"] = ["scripted: generic assurance"]
        fixes = ([{"rank": 1, "section_id": ids[0],
                   "fix": "tighten the lead"}] if ids else [])
        return json.dumps({"sections": sections, "ranked_fixes": fixes})

    return {"claim_auditor": auditor, "claim_verifier": verifier,
            "compliance_checker": compliance,
            "consistency_checker": consistency, "buyer_red_team": red_team}


def run_validation_run(tmp_root, pursuit, *, at=AT, fake=None, script=None,
                       voice_path=None):
    """The validation run alone over an existing drafted workspace. No
    try/except — a scripted kill propagates, leaving the honest state."""
    store = KBStore(tmp_root / "kb")
    log = RunLogger(pursuit.root, pursuit.new_run_id(), pursuit.pursuit_id)
    caller = TracedCaller(
        fake or FakeCaller(script or make_validation_script()), log)
    cfg = effective_config(
        extra=validation_extras(store, voice_path=voice_path))
    log.run_start(mode="dry_run", engine_version=engine_version(), config=cfg,
                  kb_snapshot=store.snapshot(),
                  research_mode=cfg["research_mode"])
    kwargs = {"voice_path": Path(voice_path)} if voice_path else {}
    report = run_validation(pursuit, caller, log, store, at=at, **kwargs)
    log.run_end(status="completed")
    return pursuit, report, log


def run_validation_package(tmp_root, *, package_id="gapcase", at=AT,
                           fake=None, script=None, **chain_kwargs):
    """Full chain: intake -> ... -> drafting (runs 0001-0005, the P7
    harness) -> validation (run_0006, the real stage)."""
    pursuit, draft_report = run_drafting_package(
        tmp_root, package_id=package_id, **chain_kwargs)
    assert draft_report.status == "complete", f"drafting refused: {draft_report}"
    return run_validation_run(tmp_root, pursuit, at=at, fake=fake,
                              script=script)
