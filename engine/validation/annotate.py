"""Annotated-draft assembly + the consumption guard (B34(11,14)).

Assembly is pure code over whitelist-gated material: every envelope
section appears in buyer order (absent-means-absent — a default becomes a
claim on screen), claims only where auditing ran, packaging derived by
counting, nothing model-written lands unverified.

consume_annotated is the liveness guard: v1's annotated-draft renderer
was orphaned by a refactor and shipped responses with no receipts,
silently. Here the slice runner's LAST step reads the artifact back and
reconciles it against the run log's validation records — the acceptance
command consumes the artifact, so it cannot be orphaned while the
acceptance command passes.
"""

import hashlib

VALIDATION_NAME = "drafts/annotated-draft.json"

CHECKS = ("claim_audit", "coverage", "consistency", "red_team", "voice_polish")


def packaging_state(all_claims: list[dict]) -> dict:
    blocks = sum(1 for c in all_claims if c.get("disposition") == "block")
    waived = sum(1 for c in all_claims if c.get("disposition") == "waived")
    return {"blocked": blocks > 0, "tier1_blocks": blocks, "waived": waived}


def build_annotated(*, envelope: dict, per_section: dict, scores: dict,
                    ranked_fixes: list[dict], validated_at: str,
                    draft_sha256: str) -> dict:
    sections = []
    all_claims: list[dict] = []
    for entry in envelope["sections"]:
        section_id = entry["section_id"]
        done = per_section.get(section_id, {})
        section = {
            "section_id": section_id,
            "title": entry.get("title", ""),
            "section_type": entry["section_type"],
            "draft_status": entry["status"],
        }
        if entry["status"] == "drafted":
            claims = done.get("claims", [])
            section["claims"] = [_claim_row(c) for c in claims]
            section["findings"] = done.get("findings", [])
            if section_id in scores:
                section["red_team"] = scores[section_id]
            all_claims.extend(claims)
        sections.append(section)
    out = {
        "pursuit_id": envelope["pursuit_id"],
        "draft_sha256": draft_sha256,
        "plan_sha256": envelope["plan_sha256"],
        "revision_n": envelope["revision_n"],
        "validated_at": validated_at,
        "packaging": packaging_state(all_claims),
        "sections": sections,
    }
    if ranked_fixes:
        out["ranked_fixes"] = ranked_fixes
    return out


def _claim_row(claim: dict) -> dict:
    row = {
        "claim_id": claim["claim_id"],
        "text": claim["text"],
        "text_digest": claim["text_digest"],
        "tier": claim["tier"],
        "status": claim["status"],
        "disposition": claim["disposition"],
    }
    if claim.get("slot_id"):
        row["slot_id"] = claim["slot_id"]
    if claim.get("fact_sheet_ref"):
        row["fact_sheet_ref"] = claim["fact_sheet_ref"]
    if claim.get("reasons"):
        row["reasons"] = claim["reasons"]
    for key in ("waived_by", "waiver_reason"):
        if claim.get(key):
            row[key] = claim[key]
    return row


def consume_annotated(pursuit, records: list[dict]) -> tuple[bool, list[str]]:
    """(ok, problems). Absence or mismatch is a nonzero slice exit — the
    orphan-detector by construction (B34(14))."""
    problems: list[str] = []
    path = pursuit.root / VALIDATION_NAME
    if not path.exists():
        return False, [f"{VALIDATION_NAME} is absent — validation produced "
                       f"no receipts"]
    try:
        annotated = pursuit.read_artifact(VALIDATION_NAME)
    except Exception as exc:  # unreadable == absent, honestly
        return False, [f"{VALIDATION_NAME} unreadable: {exc}"]

    drafted = [s for s in annotated["sections"]
               if s["draft_status"] == "drafted"]
    validation_records = [r for r in records
                          if r.get("record_type") == "validation"]
    by_check: dict[str, set] = {}
    for record in validation_records:
        check = record["validation"]["check"]
        section = (record.get("target") or {}).get("section_id")
        by_check.setdefault(check, set()).add(section)
    for check in CHECKS:
        covered = by_check.get(check, set())
        missing = [s["section_id"] for s in drafted
                   if s["section_id"] not in covered]
        if missing:
            problems.append(
                f"check {check!r} has no validation record for drafted "
                f"section(s) {missing} — receipts and trace disagree")

    counted = packaging_state(
        [c for s in drafted for c in s.get("claims", [])])
    if counted != annotated["packaging"]:
        problems.append(
            f"packaging {annotated['packaging']} does not equal the "
            f"recount over claims {counted}")
    blocked_records = [
        r for r in validation_records
        if r["validation"].get("result") == "block"]
    if annotated["packaging"]["tier1_blocks"] and not blocked_records:
        problems.append("artifact carries tier1 blocks the trace never "
                        "recorded")
    return not problems, problems


def artifact_digest(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
