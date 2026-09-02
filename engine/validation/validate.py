"""run_validation — the P8 stage (B34): five checks over the draft
envelope, per-section checkpoints, and an artifact that exists ONLY at
completion.

The cancel asymmetry is deliberate and inverse to drafting (B34(13)): a
killed drafting run keeps finished sections because a partial draft is
honest work in progress; a killed validation run leaves checkpoints (so
resume never respends) but NO annotated draft, because a partial verdict
set would dishonestly unblock packaging. The staleness clock is the
injected `at` — never the wall clock; byte-determinism holds.
"""

from dataclasses import dataclass, field
from pathlib import Path

from engine.contracts import ContractError
from engine.drafting.compose import VOICE_DEFAULT
from engine.drafting.verify import flag_present
from engine.validation import annotate, audit, checks, claims, redteam, voice
from engine.validation.findings import emit_validation, make_finding

ROOT = Path(__file__).resolve().parents[2]
ANCHORS_DEFAULT = ROOT / "config" / "references" / "win-theme-anchors.md"

STAGE = "validation"
STAGE_SPAN = "stage:validation"
DRAFT_NAME = "drafts/draft.json"
FROZEN_PLAN = "plan.frozen.json"
FROZEN_BRIEF = "brief.frozen.json"

_SYSTEM: dict[str, str] = {}


def _system(agent: str) -> str:
    if agent not in _SYSTEM:
        _SYSTEM[agent] = (ROOT / "prompts" / agent / "prompt.md").read_text(
            encoding="utf-8")
    return _SYSTEM[agent]


@dataclass
class ValidationReport:
    pursuit_id: str
    status: str = "complete"  # complete | refused
    warnings: list[str] = field(default_factory=list)
    blocked: bool = False
    tier1_blocks: int = 0
    artifact_path: Path | None = None


def _refuse(log, report, *, code: str, message: str) -> ValidationReport:
    log.emit("error", stage=STAGE, error={
        "code": code, "message": message,
        "recoverable": True, "action_taken": "surfaced_to_human"})
    report.status = "refused"
    return report


def run_validation(pursuit, caller, log, store, *, at: str,
                   voice_path: Path = VOICE_DEFAULT,
                   anchors_path: Path = ANCHORS_DEFAULT) -> ValidationReport:
    report = ValidationReport(pursuit_id=pursuit.pursuit_id)

    # --- refusal gates: zero spend --------------------------------------
    try:
        envelope = pursuit.read_artifact(DRAFT_NAME)
    except FileNotFoundError:
        return _refuse(log, report, code="missing_draft",
                       message="no drafts/draft.json — validation follows "
                               "drafting")
    if envelope.get("status") != "complete":
        return _refuse(log, report, code="draft_incomplete",
                       message="draft envelope is in_progress — a partial "
                               "draft does not validate")
    if not (pursuit.root / FROZEN_PLAN).exists():
        return _refuse(log, report, code="missing_frozen_plan",
                       message="plan.frozen.json missing")
    if not (pursuit.root / FROZEN_BRIEF).exists():
        return _refuse(log, report, code="missing_frozen_brief",
                       message="brief.frozen.json missing")
    plan_sha = pursuit.file_sha256(FROZEN_PLAN)
    if envelope.get("plan_sha256") != plan_sha:
        return _refuse(log, report, code="plan_sha_mismatch",
                       message="draft envelope binds a different frozen plan "
                               "— a re-planned pursuit voids the draft (T6)")

    try:  # verified against the gate records (P0-2)
        frozen_plan = pursuit.read_frozen("pursuit_plan")
        frozen_brief = pursuit.read_frozen("bid_brief")
    except ContractError as exc:
        return _refuse(log, report, code="frozen_verification_failed",
                       message=str(exc))
    path = frozen_plan.get("path")
    slots_by_id: dict[str, dict] = {}
    if path == "A_designated":
        try:
            container = pursuit.read_artifact(
                frozen_plan.get("slots_ref", "slots.json"))
        except FileNotFoundError:
            return _refuse(log, report, code="missing_slots",
                           message="Path A plan's slots container is missing")
        slots_by_id = {s["slot_id"]: s for s in container["slots"]}

    # Firm config: malformed raises (loader-is-the-contract); spend has
    # not started.
    anchors = redteam.load_anchors(anchors_path)
    terms = voice.prohibited_terms(voice_path)
    facts = claims.fact_catalog(store)
    facts_by_id = {c["kb_id"]: c for c in facts}
    catalog_ids = frozenset(facts_by_id)
    draft_sha = pursuit.file_sha256(DRAFT_NAME)

    # Gate-2 flag demands per section, from the frozen plan (the authority).
    # The gap->slot join is structural since E1: gap.slot_id, or section
    # scope when absent/mis-referenced (same degradation as route.py).
    flag_demand: dict[str, tuple[frozenset, bool]] = {}
    for section in frozen_plan["sections"]:
        matched: set[str] = set()
        section_level = False
        for gap in section.get("gaps", []):
            if gap.get("status") != "draft_flagged":
                continue
            slot = gap.get("slot_id")
            if slot is None or slot not in section.get("slot_ids", []):
                section_level = True
            else:
                matched.add(slot)
        flag_demand[section["section_id"]] = (frozenset(matched), section_level)

    log.emit("stage_start", stage=STAGE, span_id=STAGE_SPAN)
    ckpt = (pursuit.checkpoint_payload(STAGE)
            if STAGE in pursuit.completed_stages()
            else {"sections": {}, "cross": None, "complete": False})
    if ckpt.get("draft_sha256") != draft_sha:
        # P25 item 8 (P0-16): the checkpoint binds the envelope it was
        # built against; a different (or unrecorded) envelope starts over
        ckpt = {"sections": {}, "cross": None, "complete": False}
    ckpt["draft_sha256"] = draft_sha

    drafted = [e for e in envelope["sections"] if e["status"] == "drafted"]

    # --- per-section: claim audit + coverage + voice --------------------
    for entry in drafted:
        section_id = entry["section_id"]
        if section_id in ckpt["sections"]:
            continue
        ckpt["sections"][section_id] = validate_section(
            pursuit, caller, log, store, entry, slots_by_id, facts_by_id,
            catalog_ids, flag_demand.get(section_id, (frozenset(), False)),
            terms, at, report)
        pursuit.checkpoint(STAGE, ckpt)

    # --- cross-section: consistency + red team --------------------------
    if ckpt["cross"] is None:
        ckpt["cross"] = _cross_section(
            caller, log, envelope, drafted, slots_by_id, frozen_brief,
            anchors, report)
        pursuit.checkpoint(STAGE, ckpt)

    # Fold cross-section findings into their sections' entries.
    for entry in drafted:
        section_id = entry["section_id"]
        section_findings = ckpt["sections"][section_id]["findings"]
        seen = {f["finding_id"] for f in section_findings}
        for finding in ckpt["cross"]["findings"]:
            if finding["finding_id"].endswith(f":{section_id}") \
                    or f":{section_id}:" in finding["finding_id"]:
                if finding["finding_id"] not in seen:
                    section_findings.append(finding)
                    seen.add(finding["finding_id"])

    ckpt["complete"] = True
    pursuit.checkpoint(STAGE, ckpt)

    # --- artifact at completion ONLY (B34(13)) --------------------------
    annotated = annotate.build_annotated(
        envelope=envelope, per_section=ckpt["sections"],
        scores=ckpt["cross"]["scores"],
        ranked_fixes=ckpt["cross"]["fixes"],
        validated_at=at, draft_sha256=draft_sha)
    artifact_path = pursuit.write_artifact(
        "annotated_draft", annotated, name=annotate.VALIDATION_NAME)
    log.emit("artifact", stage=STAGE, artifact={
        "kind": "annotated_draft", "path": str(artifact_path),
        "sha256": annotate.artifact_digest(artifact_path)})

    _write_validated_status(pursuit, log, envelope)
    log.emit("stage_end", stage=STAGE)

    report.artifact_path = artifact_path
    report.blocked = annotated["packaging"]["blocked"]
    report.tier1_blocks = annotated["packaging"]["tier1_blocks"]
    return report


def _prose_maps(entry: dict) -> tuple[dict, str]:
    """(prose_by_slot for extraction gates, labeled prose for the prompt)."""
    if entry.get("answers"):
        prose_by_slot = {
            a["slot_id"]: a.get("prose", "")
            for a in entry["answers"] if a.get("prose")}
        labeled = "\n\n".join(
            f"SLOT {a['slot_id']} | ref {a.get('ref_id', '?')}:\n{a['prose']}"
            for a in entry["answers"] if a.get("prose"))
        return prose_by_slot, labeled
    prose = entry.get("prose", "")
    return {None: prose}, prose


def run_claim_audit(caller, store, *, section_id: str, section_type: str,
                    title: str, prose_by_slot: dict, labeled: str,
                    facts_by_id: dict, catalog_ids: frozenset,
                    at: str, capture: dict | None = None
                    ) -> tuple[list[dict], list[str]]:
    """The WHOLE audit path — extract, tier, verify, disposition — as one
    reusable unit: the stage runs it per section, and the poison harness
    runs the SAME function per case (B34(16): a verify-only harness cannot
    see tier-camouflage escapes; a second implementation would drift).

    `capture` is an EVAL-ONLY seam and production never passes it (proven
    by test). When supplied, the raw extraction wire and its output-token
    count are written into it.

    Why it exists (B46/P11-C4): the run log records tokens, never response
    text. So after a funded live re-baseline, a cause recorded as
    `not_extracted` could not be re-adjudicated — there would be no
    artifact showing whether the model answered at all. That turns one
    expensive run into unrepeatable evidence. Capturing the wire for the
    handful of MISSES means a mislabelled cause is re-derived offline
    instead of re-measured, which is the difference between a $0 correction
    and a $3 one."""
    target = {"section_id": section_id, "section_type": section_type}
    extraction = caller.call(
        "claim_auditor", tier="frontier",
        prompt=claims.build_extraction_prompt(
            section_title=title, labeled_prose=labeled,
            facts=list(facts_by_id.values())),
        system=_system("claim_auditor"), stage=STAGE,
        span_id=f"{section_id}:audit", parent_span=STAGE_SPAN, **target)
    if capture is not None:
        capture["extraction_wire"] = extraction.text
        capture["output_tokens"] = extraction.output_tokens
    extracted, warnings = claims.parse_extraction_wire(
        extraction.text, section_id=section_id,
        prose_by_slot=prose_by_slot, catalog_ids=catalog_ids)

    audited: list[dict] = []
    for claim in extracted:
        if claim["tier"] != 1:
            audited.append(audit.audit_claim(
                claim, verdict=None, reasons=[], fact_card=None, at=at))
            continue
        fact_card = facts_by_id.get(claim["fact_sheet_ref"] or "")
        if fact_card is None:
            audited.append(audit.audit_claim(
                claim, verdict=None, reasons=[], fact_card=None, at=at))
            continue
        _, body = store.read_card(fact_card["kb_id"])
        verify_result = caller.call(
            "claim_verifier", tier="frontier",
            prompt=audit.build_verify_prompt(claim["text"], fact_card, body),
            system=_system("claim_verifier"), stage=STAGE,
            span_id=f"{section_id}:verify:{claim['claim_id']}",
            parent_span=STAGE_SPAN, **target)
        verdict, reasons = audit.parse_verdict_wire(verify_result.text)
        audited.append(audit.audit_claim(
            claim, verdict=verdict, reasons=reasons, fact_card=fact_card,
            at=at))
    return audited, warnings


def validate_section(pursuit, caller, log, store, entry, slots_by_id,
                     facts_by_id, catalog_ids, flag_info, terms, at,
                     report) -> dict:
    """One section's checks 1-3 (claim audit -> coverage -> voice) —
    public since P9/c11: targeted re-validation (engine/revision/reval.py)
    runs exactly this over touched sections, so the round and the full
    stage can never disagree on what a section check IS."""
    section_id = entry["section_id"]
    target = {"section_id": section_id,
              "section_type": entry["section_type"]}
    prose_by_slot, labeled = _prose_maps(entry)
    all_prose = " ".join(prose_by_slot.values())

    # 1. claim audit: extract, then starved verifies.
    # The title-less fallback is a human phrase, never the section_id:
    # handing the model an identifier as the title makes it echo the id
    # as slot_id and code drops a CORRECT claim — the frame that caused
    # both P11 extraction misses (B48), closed for production and both
    # eval harnesses in the same B50 change (B49/F-11). Drafting always
    # writes a title (draft.py), so this fires only on foreign envelopes.
    audited, warnings = run_claim_audit(
        caller, store, section_id=section_id,
        section_type=entry["section_type"],
        title=entry.get("title") or "Untitled section",
        prose_by_slot=prose_by_slot,
        labeled=labeled, facts_by_id=facts_by_id, catalog_ids=catalog_ids,
        at=at)
    report.warnings.extend(warnings)

    findings = []
    for claim in audited:
        if claim["disposition"] == "block":
            findings.append(make_finding(
                check="claim_audit", rule=audit.rule_for_status(claim["status"]),
                disposition="block",
                message=f"{claim['status']}: {claim['text'][:80]!r} — "
                        + (claim["reasons"][0] if claim["reasons"] else ""),
                section_id=section_id, slot_id=claim.get("slot_id")))
        elif claim["disposition"] == "flag":
            findings.append(make_finding(
                check="claim_audit", rule=audit.rule_for_status(claim["status"]),
                disposition="review",
                message=f"stale: {claim['text'][:80]!r} — {claim['reasons'][0]}",
                section_id=section_id, slot_id=claim.get("slot_id")))
    blocked = [c for c in audited if c["disposition"] == "block"]
    stale = [c for c in audited if c["disposition"] == "flag"]
    deciding = (blocked or stale or [None])[0]
    emit_validation(
        log, check="claim_audit",
        result="block" if blocked else ("flag" if stale else "pass"),
        target=target, span_id=f"{section_id}:audit",
        parent_span=STAGE_SPAN,
        claim_tier=deciding["tier"] if deciding else None,
        claim_text_digest=deciding["text_digest"] if deciding else None,
        fact_sheet_ref=deciding.get("fact_sheet_ref") if deciding else None)

    # 2. coverage (code-first + the sub-question fast lane).
    flagged_slots, section_level_flag = flag_info
    canonical_bodies = {
        c["kb_id"]: store.read_card(c["kb_id"])[1]
        for c in entry.get("canonical", [])}
    cov = checks.coverage_findings(
        entry, slots_by_id, flagged_slots=flagged_slots,
        canonical_bodies=canonical_bodies)
    if section_level_flag and not flag_present(all_prose):
        cov.append(make_finding(
            check="coverage", rule="flag_missing", disposition="review",
            message="Gate 2 demanded [proposed approach] in this section "
                    "(unmatched gap) and no flag is present",
            section_id=section_id))
    for answer in entry.get("answers", []):
        slot = slots_by_id.get(answer["slot_id"]) or {}
        subs = slot.get("sub_questions") or []
        if subs and answer["status"] == "drafted":
            result = caller.call(
                "compliance_checker", tier="fast",
                prompt=checks.build_subq_prompt(
                    entry.get("title", section_id),
                    slot.get("question_text", ""), subs, answer["prose"]),
                system=_system("compliance_checker"), stage=STAGE,
                span_id=f"{section_id}:coverage", parent_span=STAGE_SPAN,
                **target)
            cov.extend(checks.parse_subq_wire(
                result.text, section_id=section_id,
                slot_id=answer["slot_id"], n=len(subs)))
    emit_validation(log, check="coverage",
                    result="flag" if cov else "pass", target=target,
                    span_id=f"{section_id}:coverage", parent_span=STAGE_SPAN)

    # 3. voice (deterministic).
    voiced = voice.voice_findings(section_id, all_prose, terms)
    emit_validation(log, check="voice_polish",
                    result="flag" if voiced else "pass", target=target,
                    span_id=f"{section_id}:voice", parent_span=STAGE_SPAN)

    return {
        "claims": audited,
        "findings": [f.as_dict() for f in findings + cov + voiced],
        "warnings": warnings,
    }


def consistency_pass(caller, log, drafted, slots_by_id, report) -> list:
    """Check 4 alone — cross-section BY DESIGN (a contradiction flags
    both sections), so a revise round runs it ONCE globally while
    re-running checks 1-3 per touched section (D10/G2). Public since
    P9/c11 for exactly that caller. Returns Finding objects."""
    known_ids = frozenset(e["section_id"] for e in drafted)
    prose_blocks = []
    for entry in drafted:
        _, labeled = _prose_maps(entry)
        prose_blocks.append(
            (entry["section_id"], entry.get("title", ""), labeled))

    findings = checks.cross_ref_findings(drafted, slots_by_id)
    if len(prose_blocks) >= 2:
        result = caller.call(
            "consistency_checker", tier="mid",
            prompt=checks.build_consistency_prompt(prose_blocks),
            system=_system("consistency_checker"), stage=STAGE,
            span_id="consistency", parent_span=STAGE_SPAN)
        model_findings, warnings = checks.parse_consistency_wire(
            result.text, known_ids=known_ids)
        findings.extend(model_findings)
        report.warnings.extend(warnings)
    flagged_sections = {f.section_id for f in findings}
    for entry in drafted:
        emit_validation(
            log, check="consistency",
            result="flag" if entry["section_id"] in flagged_sections
            else "pass",
            target={"section_id": entry["section_id"],
                    "section_type": entry["section_type"]},
            span_id="consistency", parent_span=STAGE_SPAN)
    return findings


def _cross_section(caller, log, envelope, drafted, slots_by_id, frozen_brief,
                   anchors, report) -> dict:
    findings = consistency_pass(caller, log, drafted, slots_by_id, report)
    known_ids = frozenset(e["section_id"] for e in drafted)
    prose_blocks = []
    for entry in drafted:
        _, labeled = _prose_maps(entry)
        prose_blocks.append(
            (entry["section_id"], entry.get("title", ""), labeled))

    buyer = frozen_brief.get("buyer", {})
    criteria = [
        f"{c.get('criterion', c)} ({c.get('weight', '?')}%)"
        if isinstance(c, dict) else str(c)
        for c in frozen_brief.get("procurement", {}).get("eval_criteria", [])]
    rt = caller.call(
        "buyer_red_team", tier="frontier",
        prompt=redteam.build_redteam_prompt(
            buyer=buyer, criteria=criteria, anchors=anchors,
            sections=prose_blocks),
        system=_system("buyer_red_team"), stage=STAGE,
        span_id="red_team", parent_span=STAGE_SPAN)
    scores, fixes, rt_findings, rt_warnings = redteam.parse_redteam_wire(
        rt.text, known_ids=known_ids)
    report.warnings.extend(rt_warnings)
    findings.extend(rt_findings)
    for entry in drafted:
        section_id = entry["section_id"]
        entry_score = scores.get(section_id, {}).get("score")
        emit_validation(
            log, check="red_team",
            result="flag" if any(
                f.rule == "weak_section" and f.section_id == section_id
                for f in rt_findings) else "pass",
            target={"section_id": section_id,
                    "section_type": entry["section_type"]},
            span_id="red_team", parent_span=STAGE_SPAN,
            score=entry_score)

    return {"findings": [f.as_dict() for f in findings],
            "scores": scores, "fixes": fixes}


def _write_validated_status(pursuit, log, envelope) -> None:
    """drafted -> validated on the LIVE plan only (the enum already carried
    the value; B34's writer). Frozen plan byte-untouched, as ever."""
    import hashlib as _h
    plan_live = pursuit.read_artifact("plan.json")
    validated = {e["section_id"] for e in envelope["sections"]
                 if e["status"] == "drafted"}
    changed = False
    for section in plan_live.get("sections", []):
        if section.get("draft_status") == "drafted" \
                and section["section_id"] in validated:
            section["draft_status"] = "validated"
            changed = True
    if changed:
        plan_path = pursuit.write_artifact("pursuit_plan", plan_live)
        log.emit("artifact", stage=STAGE, artifact={
            "kind": "pursuit_plan", "path": str(plan_path),
            "sha256": _h.sha256(plan_path.read_bytes()).hexdigest()})
