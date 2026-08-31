"""Buyer Red-Team (B34(9)): one frontier call, ADVISORY by decree — no
gate consumes it, no acceptance clause names it, because an uncalibrated
judge gating anything is decoration (E5; calibration is A4). But advisory
never means the record lies: weak sections get result="flag", every
section gets its score recorded, and the ranked fixes land in the
annotated draft labeled ADVISORY. Scores are clamped by code; ranks are
re-derived from wire order; ids are whitelisted.
"""

import json

from engine.validation.findings import Finding, make_finding

REDTEAM_TASK = "Task: red-team."

WEAK_SCORE = 5  # score < WEAK_SCORE -> result "flag" + weak_section finding

RUBRIC_ID = "rt_v1"  # carried in the config extra; the rubric text lives in
                     # prompts/buyer_red_team/prompt.md (digest-covered)


def load_anchors(path) -> str:
    """config/references/win-theme-anchors.md — loader-is-the-contract:
    H1 pinned + at least one Strong/Weak pair present."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("# Win-theme quality anchors"):
        raise ValueError(f"{path}: expected the pinned H1 title")
    if "**Strong**" not in text or "**Weak**" not in text:
        raise ValueError(f"{path}: needs at least one Strong/Weak anchor pair")
    return text


def build_redteam_prompt(*, buyer: dict, criteria: list, anchors: str,
                         sections: list[tuple[str, str, str]]) -> str:
    """Persona from the frozen brief's own fields; the buyer's own eval
    criteria; the anchors frame what strong looks like. sections =
    (section_id, title, prose)."""
    criteria_lines = "\n".join(f"- {c}" for c in criteria) or "- (none stated)"
    blocks = "\n\n".join(
        f"SECTION {section_id}: {title}\n{prose}"
        for section_id, title, prose in sections)
    return (
        f"{REDTEAM_TASK}\n\n"
        f"You are the buyer: {buyer.get('name', 'the buyer')} — "
        f"{buyer.get('vertical', '')}. You are evaluating this response "
        f"against your own published criteria:\n{criteria_lines}\n\n"
        f"What strong looks like (anchors):\n{anchors}\n\n"
        f"THE DRAFT:\n{blocks}\n\n"
        f'Return JSON only: {{"sections": [{{"section_id": "<id>", '
        f'"score": <0-10>, "weaknesses": ["<specific weakness>"]}}], '
        f'"ranked_fixes": [{{"rank": 1, "section_id": "<id>", '
        f'"fix": "<the single highest-value fix>"}}]}}'
    )


def parse_redteam_wire(text: str, *, known_ids: frozenset[str]
                       ) -> tuple[dict[str, dict], list[dict],
                                  list[Finding], list[str]]:
    """(scores_by_section, ranked_fixes, findings, warnings). Unknown ids
    dropped-and-reported; scores clamped 0-10 with a warning; ranks
    re-derived from order — the model proposes, code decides."""
    warnings: list[str] = []
    try:
        wire = json.loads(text)
        rows = wire["sections"]
        assert isinstance(rows, list)
    except (ValueError, KeyError, AssertionError, TypeError):
        return {}, [], [], ["red-team wire unparseable — advisory scores "
                            "unavailable this run (recorded, not faked)"]
    scores: dict[str, dict] = {}
    findings: list[Finding] = []
    for row in rows:
        section_id = row.get("section_id") if isinstance(row, dict) else None
        if section_id not in known_ids:
            warnings.append(f"red-team row for unknown section "
                            f"{section_id!r} dropped")
            continue
        raw = row.get("score")
        score = raw if isinstance(raw, (int, float)) else 0
        clamped = max(0, min(10, score))
        if clamped != raw:
            warnings.append(f"{section_id}: score {raw!r} clamped to {clamped}")
        weaknesses = [str(w) for w in row.get("weaknesses", [])
                      if isinstance(w, str)][:5]
        scores[section_id] = {"score": clamped, "weaknesses": weaknesses}
        if clamped < WEAK_SCORE:
            findings.append(make_finding(
                check="red_team", rule="weak_section", disposition="advisory",
                message=f"buyer-persona score {clamped}/10"
                        + (f": {weaknesses[0]}" if weaknesses else ""),
                section_id=section_id))
    fixes: list[dict] = []
    for row in wire.get("ranked_fixes", []) or []:
        if not isinstance(row, dict) or row.get("section_id") not in known_ids:
            warnings.append("ranked fix with unknown section dropped")
            continue
        fixes.append({"rank": len(fixes) + 1,  # re-derived, never trusted
                      "section_id": row["section_id"],
                      "fix": str(row.get("fix", ""))[:400]})
    return scores, fixes, findings, warnings
