"""Claim extraction: the fact-sheet catalog + the extraction wire's code
gates (B34(5)).

The model PROPOSES claims; code decides what lands. Gates, in order: the
claim text must appear whitespace-normalized in the DELIVERED prose (a
claim the prose doesn't contain is a hallucination — dropped and
reported); the proposed fact_sheet_ref must be a real catalog id (an
invented ref is treated as no-referent, which BLOCKS for Tier-1 rather
than trusting the invention); the tier must be 1, 2, or 3; the slot_id
must be one the section owns. Claim ids are code-assigned in wire order —
never model-claimed.
"""

import hashlib
import json

from engine.drafting.verify import normalize_ws

EXTRACT_TASK = "Task: extract claims."


def fact_catalog(store) -> list[dict]:
    """Every fact_sheet-layer card, kb_id order — the auditor's verification
    base. Read directly from the store: card_search deliberately cannot see
    this layer (B34(26)), and the auditor deliberately does not search.

    A generated-description card can never appear here (WP13 R13/X10 via
    B59's structural lever): the schema refuses the layer/content_origin
    combination at every validated write, and this filter is the belt
    against a hand-edited store — Tier-1 grounds only in human-verified
    fact cards, and a claim whose ref is filtered out audits as
    no-referent, which BLOCKS. Deliberately NOT part of the eval scoring
    roster (engine/evals/cases.py), so the recorded poison and
    claim-extraction baselines are untouched by this belt."""
    return [c for c in store.list_cards()
            if c.get("layer") == "fact_sheet"
            and c.get("content_origin") != "generated_description"]


def catalog_lines(facts: list[dict]) -> str:
    return "\n".join(
        f"FACT {card['kb_id']}: {card.get('title', '')} — {card['summary']}"
        for card in facts
    )


def claim_digest(text: str) -> str:
    return hashlib.sha256(normalize_ws(text).encode("utf-8")).hexdigest()[:16]


def build_extraction_prompt(*, section_title: str, labeled_prose: str,
                            facts: list[dict]) -> str:
    """Labeled section prose + the fact catalog + the wire demand. The
    system prompt (prompts/claim_auditor/prompt.md) carries the tiering
    rules; this user prompt carries only the material."""
    return (
        f"{EXTRACT_TASK}\n\n"
        f"Section: {section_title}\n\n"
        f"DRAFTED PROSE (extract claims from this text only):\n"
        f"{labeled_prose}\n\n"
        f"FACT SHEET CATALOG (propose fact_sheet_ref only from these ids):\n"
        f"{catalog_lines(facts)}\n\n"
        f'Return JSON only: {{"claims": [{{"slot_id": "<slot id or null>", '
        f'"text": "<verbatim sentence or clause>", "tier": 1, '
        f'"fact_sheet_ref": "<kb_id or null>"}}]}}'
    )


def parse_extraction_wire(text: str, *, section_id: str,
                          prose_by_slot: dict[str | None, str],
                          catalog_ids: frozenset[str]
                          ) -> tuple[list[dict], list[str]]:
    """Whitelist parse -> (claims, warnings). Every dropped row is reported
    (drop-and-report, B21(4) lineage); nothing is dropped silently."""
    warnings: list[str] = []
    try:
        wire = json.loads(text)
        rows = wire["claims"]
        assert isinstance(rows, list)
    except (ValueError, KeyError, AssertionError, TypeError):
        # TypeError: json.loads accepts scalar documents — the live model
        # has submitted literal `null` (P8 live run) and subscripting a
        # non-object must degrade to unextracted, never crash the audit.
        return [], [f"{section_id}: claim-extraction wire unparseable — "
                    f"section audits as unextracted"]

    normalized_prose = {
        slot: normalize_ws(prose) for slot, prose in prose_by_slot.items()
    }
    claims: list[dict] = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("text"), str):
            warnings.append(f"{section_id}: malformed claim row dropped")
            continue
        claim_text = row["text"].strip()
        slot_id = row.get("slot_id")
        if slot_id is not None and slot_id not in normalized_prose:
            warnings.append(
                f"{section_id}: claim for unknown slot {slot_id!r} dropped")
            continue
        holders = ([slot_id] if slot_id is not None
                   else list(normalized_prose))
        # Distinct sentinel: None is a legitimate holder key (Path B
        # section prose), so absence must not be spelled None.
        _missing = object()
        containing = next(
            (h for h in holders
             if normalize_ws(claim_text) in normalized_prose[h]), _missing)
        if normalize_ws(claim_text) == "" or containing is _missing:
            warnings.append(
                f"{section_id}: claim text not present in delivered prose — "
                f"dropped (hallucinated claim): {claim_text[:60]!r}")
            continue
        tier = row.get("tier")
        if tier not in (1, 2, 3):
            warnings.append(
                f"{section_id}: claim with invalid tier {tier!r} dropped")
            continue
        ref = row.get("fact_sheet_ref")
        if ref is not None and ref not in catalog_ids:
            warnings.append(
                f"{section_id}: proposed fact_sheet_ref {ref!r} is not in "
                f"the catalog — treated as no referent")
            ref = None
        claims.append({
            "claim_id": f"c_{section_id}_{len(claims) + 1:02d}",
            "slot_id": containing if slot_id is not None else None,
            "text": claim_text,
            "text_digest": claim_digest(claim_text),
            "tier": tier,
            "fact_sheet_ref": ref,
        })
    return claims, warnings
