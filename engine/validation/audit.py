"""Starved per-claim verification + the disposition map + the staleness
clock (B34(1,2,6)).

The verify prompt is ONE claim and ONE fact card, nothing else — no RFP,
no win themes, no surrounding argument (v1: starve the verifier of the
motive and it has nothing to be persuaded by; zero false flags live).
Verdicts are the enum, never confidence scores; whether a claim needs
review is derived by CODE from the verdict, never self-reported.

Dispositions (Tier-1): UNSUPPORTED / MISATTRIBUTED / OVERSTATED /
no-referent / unparseable-verdict -> BLOCK (waivable, Q2); SUPPORTED on a
card whose review_due has lapsed -> STALE, flag; SUPPORTED otherwise ->
pass. Tier-2/3 claims are tiered and recorded, never verified
(not_audited) — verification is Tier-1's control. An unparseable verdict
is never an approval; the verifier flags and never approves.
"""

import json

VERIFY_TASK = "Task: verify."

VERDICTS = ("SUPPORTED", "OVERSTATED", "UNSUPPORTED", "MISATTRIBUTED")

_BLOCK_STATUS = {
    "OVERSTATED": "overstated",
    "UNSUPPORTED": "unsupported",
    "MISATTRIBUTED": "misattributed",
}

_RULE_FOR_STATUS = {
    "overstated": "tier1_overstated",
    "unsupported": "tier1_unsupported",
    "misattributed": "tier1_misattributed",
    "unverifiable": "tier1_unverifiable",
    "stale": "tier1_stale",
}


def rule_for_status(status: str) -> str:
    return _RULE_FOR_STATUS[status]


def build_verify_prompt(claim_text: str, fact_card: dict, fact_body: str) -> str:
    """STARVED by design: adding any surrounding context here would hand the
    verifier the drafter's motive. Keep it one claim, one card."""
    return (
        f"{VERIFY_TASK}\n\n"
        f"CLAIM: {claim_text}\n\n"
        f"EVIDENCE CARD {fact_card['kb_id']} "
        f"(owner: {fact_card.get('owner', '?')}, "
        f"verified: {fact_card.get('verified_date', '?')}):\n"
        f"{fact_body}\n\n"
        f'Return JSON only: {{"verdict": "SUPPORTED|OVERSTATED|UNSUPPORTED|'
        f'MISATTRIBUTED", "reasons": ["<quote the deciding words>"]}}'
    )


def parse_verdict_wire(text: str) -> tuple[str | None, list[str]]:
    """(verdict, reasons). Anything outside the enum is None — and None is
    never an approval (the caller blocks on it)."""
    try:
        wire = json.loads(text)
        verdict = wire.get("verdict")
        reasons = wire.get("reasons") or []
        if verdict in VERDICTS and isinstance(reasons, list):
            return verdict, [str(r) for r in reasons]
    except (ValueError, AttributeError, TypeError):
        # AttributeError/TypeError: a valid-JSON scalar (`null`) has no
        # .get, and an unhashable verdict cannot be tested against the
        # enum — both degrade to None, and None is never an approval.
        pass
    return None, []


def is_stale(fact_card: dict, at: str) -> bool:
    """The tier1_unverified clock (B34(6)): `at` is the injected ISO
    datetime run_validation received — never the wall clock. ISO dates
    compare lexicographically."""
    review_due = fact_card.get("review_due")
    return bool(review_due) and review_due < at[:10]


def audit_claim(claim: dict, *, verdict: str | None, reasons: list[str],
                fact_card: dict | None, at: str) -> dict:
    """The disposition map (B34(2)) — pure code over the verdict enum.
    Returns the claim with status/disposition/reasons set."""
    out = dict(claim)
    if claim["tier"] != 1:
        out.update(status="not_audited", disposition="pass", reasons=[])
        return out
    if fact_card is None:
        out.update(
            status="unverifiable", disposition="block",
            reasons=["no fact-sheet referent — an unverifiable bindable "
                     "claim blocks packaging until waived (B34(6))"])
        return out
    if verdict is None:
        out.update(
            status="unverifiable", disposition="block",
            reasons=["verifier verdict unparseable — not an approval"])
        return out
    if verdict == "SUPPORTED":
        if is_stale(fact_card, at):
            out.update(
                status="stale", disposition="flag",
                reasons=[f"supported by {fact_card['kb_id']} whose "
                         f"review_due {fact_card.get('review_due')} has "
                         f"lapsed — re-verify the fact"])
            return out
        out.update(status="supported", disposition="pass", reasons=reasons)
        return out
    out.update(status=_BLOCK_STATUS[verdict], disposition="block",
               reasons=reasons)
    return out
