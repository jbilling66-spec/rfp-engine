"""The headless Tier-1 waiver lane (B34(15)) — Q2's "waivable, logged"
made concrete. Approve-style contract (B22(6) lineage): idempotent-
convergent, every waiver on the trace with actor + reason, and the
artifact's packaging state recomputed by counting, never edited by hand.
A boilerplate reason emits the registered tier1_waiver_rate alert
condition as a warning — an unlogged-in-spirit waiver is a hole in the
Q2 control even when the fields are technically present.
"""

from dataclasses import dataclass, field

from engine.validation import annotate
from engine.validation.findings import emit_validation

_BOILERPLATE = {"ok", "okay", "approved", "fine", "yes", "waived", "done"}


@dataclass
class WaiverResult:
    claim_id: str
    status: str  # waived | already_waived | refused
    warnings: list[str] = field(default_factory=list)
    section_id: str | None = None  # P26c: the waive_block event names it


def approve_waiver(pursuit, log, *, claim_id: str, actor: str, reason: str,
                   at: str) -> WaiverResult:
    result = WaiverResult(claim_id=claim_id, status="refused")
    try:
        annotated = pursuit.read_artifact(annotate.VALIDATION_NAME)
    except FileNotFoundError:
        result.warnings.append("no annotated draft — nothing to waive")
        return result

    target_claim = None
    target_section = None
    for section in annotated["sections"]:
        for claim in section.get("claims", []):
            if claim["claim_id"] == claim_id:
                target_claim, target_section = claim, section
    if target_claim is None:
        result.warnings.append(f"claim {claim_id!r} not in the annotated draft")
        return result
    result.section_id = target_section["section_id"]
    if target_claim["disposition"] == "waived":
        result.status = "already_waived"  # idempotent-convergent (B22(10))
        return result
    if target_claim["disposition"] != "block":
        result.warnings.append(
            f"claim {claim_id!r} is {target_claim['disposition']!r} — only "
            f"blocking claims are waivable")
        return result

    if not reason.strip() or reason.strip().lower() in _BOILERPLATE \
            or len(reason.strip()) < 10:
        # The registered alert condition (tier1_waiver_rate): recorded and
        # surfaced, not refused — the human owns the call, the record owns
        # the smell.
        result.warnings.append(
            f"waiver reason {reason!r} is empty or boilerplate — the "
            f"tier1_waiver_rate alert condition (record a real reason)")

    original = target_claim["status"]
    target_claim.setdefault("reasons", []).insert(
        0, f"waived over {original} by {actor} at {at}")
    target_claim["status"] = "waived"
    target_claim["disposition"] = "waived"
    target_claim["waived_by"] = actor
    target_claim["waiver_reason"] = reason

    all_claims = [c for s in annotated["sections"]
                  for c in s.get("claims", [])]
    annotated["packaging"] = annotate.packaging_state(all_claims)
    pursuit.write_artifact("annotated_draft", annotated,
                           name=annotate.VALIDATION_NAME)

    emit_validation(
        log, check="claim_audit", result="waived",
        target={"section_id": target_section["section_id"],
                "section_type": target_section["section_type"]},
        claim_tier=target_claim["tier"],
        claim_text_digest=target_claim["text_digest"],
        fact_sheet_ref=target_claim.get("fact_sheet_ref"),
        waived_by=actor, waiver_reason=reason)
    result.status = "waived"
    return result
