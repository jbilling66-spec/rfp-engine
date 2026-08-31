"""The findings contract + the one validation-record choke point (B34(4,12)).

A finding carries its reason (a boolean that cannot say why is a defect),
a deterministic id (waivers and Gate-3-style acknowledgements key on it),
and a disposition. One rule, one owning check — the RULE_OWNERS bijection
is test-asserted, so no two checks can report the same defect twice (a
list that says the same thing twice is a list that gets skimmed).

emit_validation() is the only writer of validation run-log records in the
engine: ONLY claim_audit may emit result="block" (spec Q2 made structural
— it also keeps the totals.tier1_blocks counter honest, which increments
on ANY block). Every declared blocking rule has a fixture that fires this
guard; v1 shipped a dead blocking branch for weeks because none did.
"""

from dataclasses import dataclass

from engine.contracts import ContractError

BLOCK_CAPABLE_CHECK = "claim_audit"

# rule -> owning check. A rule appearing under two checks is a registry
# defect; the bijection test enforces it.
RULE_OWNERS: dict[str, str] = {
    # claim_audit
    "tier1_unsupported": "claim_audit",
    "tier1_misattributed": "claim_audit",
    "tier1_overstated": "claim_audit",
    "tier1_unverifiable": "claim_audit",
    "tier1_stale": "claim_audit",
    # coverage
    "slot_unanswered": "coverage",
    "length_exceeded": "coverage",
    "flag_missing": "coverage",
    "canonical_violated": "coverage",
    "omission_line_missing": "coverage",
    "constraint_review": "coverage",
    "sub_question_unaddressed": "coverage",
    # consistency
    "cross_ref_dangling": "consistency",
    "contradiction": "consistency",
    # red_team (advisory)
    "weak_section": "red_team",
    # voice_polish
    "prohibited_word": "voice_polish",
}


@dataclass(frozen=True)
class Finding:
    check: str
    rule: str
    disposition: str  # advisory | review | block
    message: str
    section_id: str
    slot_id: str | None = None

    @property
    def finding_id(self) -> str:
        base = f"{self.check}:{self.rule}:{self.section_id}"
        return f"{base}:{self.slot_id}" if self.slot_id else base

    def as_dict(self) -> dict:
        out = {
            "finding_id": self.finding_id,
            "check": self.check,
            "rule": self.rule,
            "disposition": self.disposition,
            "message": self.message,
        }
        if self.slot_id:
            out["slot_id"] = self.slot_id
        return out


def make_finding(*, check: str, rule: str, disposition: str, message: str,
                 section_id: str, slot_id: str | None = None) -> Finding:
    owner = RULE_OWNERS.get(rule)
    if owner is None:
        raise ContractError(f"finding rule {rule!r} is not in RULE_OWNERS")
    if owner != check:
        raise ContractError(
            f"rule {rule!r} belongs to {owner!r}, not {check!r} — one rule, "
            f"one owning check (no-double-report)")
    if disposition == "block" and check != BLOCK_CAPABLE_CHECK:
        raise ContractError(
            f"{check!r} may not raise a blocking finding — only "
            f"{BLOCK_CAPABLE_CHECK!r} blocks (Q2, B34(4))")
    return Finding(check=check, rule=rule, disposition=disposition,
                   message=message, section_id=section_id, slot_id=slot_id)


def dedupe(findings: list[Finding]) -> list[Finding]:
    """First occurrence wins — Gate-3-style acknowledgement is by id, and a
    duplicated id would let one acknowledgement clear two defects."""
    seen: set[str] = set()
    out: list[Finding] = []
    for finding in findings:
        if finding.finding_id not in seen:
            seen.add(finding.finding_id)
            out.append(finding)
    return out


def emit_validation(log, *, check: str, result: str, target: dict,
                    span_id: str | None = None,
                    parent_span: str | None = None, **payload) -> int:
    """The engine's only validation-record writer. Section grain (B34(3)):
    one record per check per section; per-claim receipts live in the
    annotated draft, not the trace."""
    if result == "block" and check != BLOCK_CAPABLE_CHECK:
        raise ContractError(
            f"validation record with result='block' from {check!r} — only "
            f"{BLOCK_CAPABLE_CHECK!r} may block (Q2, B34(4)); a foreign "
            f"block would also corrupt totals.tier1_blocks")
    validation = {"check": check, "result": result}
    validation.update({k: v for k, v in payload.items() if v is not None})
    fields: dict = {"stage": "validation", "validation": validation,
                    "target": target}
    if span_id:
        fields["span_id"] = span_id
    if parent_span:
        fields["parent_span"] = parent_span
    return log.emit("validation", **fields)
