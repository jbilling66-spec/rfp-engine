"""The exit-door binding check (P25 item 8; register P0-16, P0-2, P0-20).

Every buyer-facing lane runs through `assert_current` ONCE per request,
at the door: the frozen plan verifies against its gate record (P0-2),
the draft envelope binds the LIVE freeze and the annotated draft binds
the LIVE envelope (P0-16 — a replanned pursuit's pre-amendment response
can never ship), and packaging is not blocked (P0-20 — the block used to
be enforced on the render lane only, while the template-fill lane wrote
the same submission file unchecked). The submission render additionally
refuses drafted-owed sections that still pend a disposition; the
write-back lanes record every refused slot in their facts instead, so a
pend there is recorded absence, not a silent hole.
"""

from engine.contracts import ContractError

LANES = ("submission", "review", "writeback")


def owed_pends(envelope) -> list[str]:
    return sorted({e["section_id"] for e in envelope.get("sections", [])
                   if e.get("status") == "awaiting_disposition"
                   or any(a.get("status") == "awaiting_disposition"
                          for a in e.get("answers", []))})


def assert_current(pursuit, *, lane: str) -> tuple[dict, dict]:
    """Refuse (ContractError, naming WHICH binding broke) unless the
    workspace's buyer-facing state is current. Returns (envelope,
    annotated). A missing file raises FileNotFoundError, which every
    door already maps to 409."""
    if lane not in LANES:
        raise ValueError(f"lane must be one of {LANES}, got {lane!r}")
    frozen_sha = pursuit.file_sha256("plan.frozen.json")
    if frozen_sha is None:
        raise FileNotFoundError(pursuit.root / "plan.frozen.json")
    pursuit.read_frozen("pursuit_plan")  # verified against gate_2 (P0-2)
    envelope = pursuit.read_artifact("drafts/draft.json")
    if envelope.get("plan_sha256") != frozen_sha:
        raise ContractError(
            "the draft envelope binds a different frozen plan "
            "(draft.plan_sha256 differs from the live plan.frozen.json) — a "
            "replanned pursuit voids its draft; advance to draft against "
            "the current plan (P0-16)")
    annotated = pursuit.read_artifact("drafts/annotated-draft.json")
    if annotated.get("draft_sha256") != pursuit.file_sha256(
            "drafts/draft.json"):
        raise ContractError(
            "the annotated draft does not match the live envelope "
            "(annotated.draft_sha256 differs from drafts/draft.json) — "
            "re-run validation (P0-16)")
    if lane == "review":
        return envelope, annotated  # the internal reader gets the whole truth
    packaging = annotated.get("packaging", {})
    if packaging.get("blocked"):
        raise ContractError(
            f"packaging is BLOCKED ({packaging.get('tier1_blocks', 0)} "
            "tier-1 block(s)) — no buyer-facing lane opens under a block; "
            "waive or revise first (P0-20)")
    if lane == "submission":
        pends = owed_pends(envelope)
        if pends:
            raise ContractError(
                "drafted-owed section(s) still pend gap dispositions: "
                + ", ".join(pends) + " — a submission with silent holes "
                "would misrepresent the response")
    return envelope, annotated
