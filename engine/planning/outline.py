"""Path B — the Outline Architect stage: the one model call in
planning (frontier; genuinely new work, no v1 ancestor).

Model proposes, code writes (B22(3) citedness pattern): the wire is
whitelist-parsed — based_on ⊆ reference ids, requirement_refs ⊆ matrix
refs, win_themes ⊆ approved — every violation dropped-and-reported,
never kept. Section ids are code-slugged; wire order is preserved
(B22(4)). The architect's `purpose` line steers mapping and obligation
matching in-stage and is deliberately NOT stored on the plan (the
schema carries title only — B28).
"""

import hashlib
import json
from pathlib import Path

from engine.contracts import ContractError
from engine.kb import card_search
from engine.llm.frames import wrap_brief_context, wrap_lead_context, wrap_reference
from engine.planning.confidence import RETRIEVAL_FLOOR, confidence, verdict
from engine.planning.mapper import compose_ping, map_sections
from engine.planning.obligations import match as match_obligations
from engine.planning.precedent import attach_precedents, scan_prior_plans
from engine.planning.reference import load_reference, render_reference
from engine.planning.sections import unique_slugs

ROOT = Path(__file__).resolve().parents[2]
_PROMPT = ROOT / "prompts" / "outline_architect" / "prompt.md"

MIN_SECTIONS = 3


def brief_digest(frozen: dict) -> str:
    """Code-owned, only-present-fields (themes.py precedent). The exact
    line formats are the derive-wire fixture's parse targets — change
    them and the frame-drift tests fail together, never silently apart."""
    buyer = frozen.get("buyer", {})
    procurement = frozen.get("procurement", {})
    lines: list[str] = []
    if buyer.get("name"):
        vertical = f" ({buyer['vertical']})" if buyer.get("vertical") else ""
        lines.append(f"Buyer: {buyer['name']}{vertical}")
    if buyer.get("profile"):
        lines.append(f"Profile: {buyer['profile']}")
    if procurement.get("what_is_bought"):
        lines.append(f"What is bought: {procurement['what_is_bought']}")
    if buyer.get("terminology"):
        lines.append("Buyer terminology: " + "; ".join(buyer["terminology"]))
    approved = frozen.get("win_themes", {}).get("approved", [])
    if approved:
        lines.append("Approved win themes:")
        lines.extend(f"* {theme}" for theme in approved)
    matrix = frozen.get("requirements_matrix", [])
    if matrix:
        lines.append("Requirements matrix:")
        for row in matrix:
            ref = row.get("ref", "(no ref)")
            lines.append(f"- {ref} | {row.get('requirement', '')}")
    return "\n".join(lines)


def parse_wire_outline(text: str, *, reference_ids: set[str],
                       matrix_refs: set[str], approved: list[str]
                       ) -> tuple[list[dict], list[dict], list[str]]:
    """-> (schema-shaped sections, purposes-by-index, warnings). Raises
    ContractError on unparseable JSON or zero usable sections."""
    try:
        wire = json.loads(text)
    except json.JSONDecodeError as e:
        raise ContractError(f"outline_architect returned unparseable JSON: {e}")
    entries = wire.get("sections")
    if not isinstance(entries, list) or not entries:
        raise ContractError("outline_architect returned no sections")

    warnings: list[str] = []
    kept: list[dict] = []
    purposes: list[str] = []
    approved_set = set(approved)
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict) or not entry.get("title"):
            warnings.append(f"outline entry {i}: no title — dropped")
            continue
        section: dict = {"title": str(entry["title"]).strip()}
        source = entry.get("source")
        if source not in ("firm_reference", "architect_added"):
            warnings.append(
                f"outline entry {i}: source {source!r} coerced to "
                "architect_added"
            )
            source = "architect_added"
        based_on = [b for b in entry.get("based_on", []) if b in reference_ids]
        removed = [b for b in entry.get("based_on", []) if b not in reference_ids]
        if removed:
            warnings.append(
                f"{section['title']}: based_on outside the reference "
                f"dropped: {removed}"
            )
        refs = [r for r in entry.get("requirement_refs", []) if r in matrix_refs]
        bad_refs = [r for r in entry.get("requirement_refs", [])
                    if r not in matrix_refs]
        if bad_refs:
            warnings.append(
                f"{section['title']}: requirement_refs outside the matrix "
                f"dropped: {bad_refs}"
            )
        themes = [t for t in entry.get("win_themes", []) if t in approved_set]
        bad_themes = [t for t in entry.get("win_themes", [])
                      if t not in approved_set]
        if bad_themes:
            warnings.append(
                f"{section['title']}: win_themes outside the approved set "
                f"dropped: {bad_themes}"
            )
        section["source"] = source
        if refs:
            section["requirement_refs"] = sorted(set(refs))
        if themes:
            section["win_themes"] = themes
        # Adaptation provenance goes on the section itself — the plan
        # schema gained the carrier at P9/E1 (B28(8) closed). Absent
        # means the section answers the buyer/architect, not the reference.
        if based_on:
            section["based_on"] = based_on
        kept.append(section)
        purposes.append(str(entry.get("purpose", "")).strip())

    if not kept:
        raise ContractError("outline_architect: every section was dropped")
    if len(kept) < MIN_SECTIONS:
        warnings.append(
            f"outline has only {len(kept)} sections — thin for a full "
            "response (kept; the human decides at Gate 2)"
        )
    for section, sid in zip(kept, unique_slugs([s["title"] for s in kept])):
        section["section_id"] = sid
    return kept, purposes, warnings


def _map_outline(store, sections: list[dict], purposes: list[str],
                 *, log) -> None:
    """Per-section grounding: one search on title + purpose. Same
    verdict vocabulary as Path A; empty is decided here."""
    for section, purpose in zip(sections, purposes):
        query = f"{section['title']} {purpose}".strip()
        result = card_search(store, query, log=log, stage="path_b_outline",
                             agent="kb_mapper",
                             target={"section_id": section["section_id"]})
        scores = [r.score for r in result.results]
        call = verdict(scores)
        if call == "grounded":
            section["kb_hits"] = [
                {"kb_id": r.kb_id, "confidence": confidence(r.score)}
                for r in sorted(result.results,
                                key=lambda r: (-r.score, r.kb_id))
                if r.score >= RETRIEVAL_FLOOR
            ]
        else:
            section["gaps"] = [{
                "kind": call,
                "question_to_human": compose_ping(
                    section["title"], section["section_id"],
                    purpose or section["title"],
                    excluded_count=len(result.excluded),
                ),
                "status": "open",
            }]


def run_path_b(pursuit, caller, log, store, frozen: dict, manifest, feedback,
               reference_path: Path, report):
    """The guarded Path-B stage. Returns a refused report or None."""
    from engine.planning.plan import _number_and_emit_gaps

    outline = load_reference(reference_path)  # firm config: raises loud
    log.emit("stage_start", stage="path_b_outline")

    approved = frozen.get("win_themes", {}).get("approved", [])
    matrix_refs = {
        row["ref"] for row in frozen.get("requirements_matrix", [])
        if row.get("ref")
    }
    parts = ["Task: outline.", wrap_brief_context(brief_digest(frozen))]
    if feedback:
        parts.append(wrap_lead_context(feedback))
    parts.append(wrap_reference(render_reference(outline)))
    result = caller.call("outline_architect", tier="frontier",
                         prompt="\n\n".join(parts),
                         system=_PROMPT.read_text(encoding="utf-8"),
                         stage="path_b_outline")

    sections, purposes, warnings = parse_wire_outline(
        result.text, reference_ids=set(outline.ids()),
        matrix_refs=matrix_refs, approved=approved,
    )
    report.warnings.extend(warnings)

    # P16/C7: the template's parsed slots ride the plan. A section
    # based_on template sections inherits their TargetSlots (order
    # preserved, deduped); an architect_added section has none — its
    # creative freedom is the point (the owner's v2 pivot), so it grounds by
    # title+purpose as before.
    from engine.contracts import validate
    from engine.structure import merge_parsed

    ref_by_id = {s["id"]: s for s in outline.sections}
    slots_by_id = {s["slot_id"]: s for s in outline.parsed.slots}
    for section in sections:
        ids: list[str] = []
        for ref in section.get("based_on", []):
            ids.extend(ref_by_id[ref]["slot_ids"])
        section["slot_ids"] = list(dict.fromkeys(ids))

    for slot in outline.parsed.slots:
        validate("target_slot", slot)
    container = {"pursuit_id": pursuit.pursuit_id,
                 **merge_parsed([outline.parsed])}
    slots_path = pursuit.write_artifact("target_slots", container,
                                        name="slots.json")
    log.emit("artifact", stage="path_b_outline", artifact={
        "kind": "target_slots",
        "path": str(slots_path),
        "sha256": hashlib.sha256(slots_path.read_bytes()).hexdigest(),
    })

    slotted = [s for s in sections if s["slot_ids"]]
    bare = [(s, p) for s, p in zip(sections, purposes)
            if not s["slot_ids"]]
    if slotted:
        map_sections(store, slotted, slots_by_id,
                     log=log, stage="path_b_outline")
    _map_outline(store, [s for s, _ in bare], [p for _, p in bare],
                 log=log)

    texts_by_section = {
        s["section_id"]: [p] if p else []
        for s, p in zip(sections, purposes)
    }
    obligations = match_obligations(manifest, sections, texts_by_section)
    _number_and_emit_gaps(pursuit, log, "path_b_outline", sections,
                          obligations, slots_by_id=slots_by_id)

    priors, skipped = scan_prior_plans(pursuit.root.parent,
                                       self_id=pursuit.pursuit_id)
    report.warnings.extend(skipped)
    # Path B matches on section titles only (B28): purposes are prose,
    # not identity.
    attach_precedents(sections, priors, texts_by_section={})

    total = len(frozen.get("requirements_matrix", []))
    covered_refs = {
        ref for s in sections for ref in s.get("requirement_refs", [])
    }
    open_gaps = sum(len(s.get("gaps", [])) for s in sections)
    payload = {
        "sections": sections,  # based_on rides the sections now (E1)
        "obligations": obligations,
        "coverage": {
            "total_requirements": total,
            "covered": len(covered_refs),
            "open_gaps": open_gaps,
            "omit_approved": 0,
            "draft_flagged": 0,
        },
        "warnings": report.warnings,
        # the reference IS the template file now (P16/C7)
        "reference_sha256": hashlib.sha256(
            Path(reference_path).read_bytes()
        ).hexdigest(),
        "slots_sha256": hashlib.sha256(slots_path.read_bytes()).hexdigest(),
        "slot_count": container["slot_count"],
        "source_sha256": container["source_sha256"],
    }
    if feedback:
        payload["rejection_feedback"] = feedback
    pursuit.checkpoint("path_b_outline", payload)
    log.emit("stage_end", stage="path_b_outline")
    return None
