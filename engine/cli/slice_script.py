"""The CI slice's FakeCaller script (B34(24)) — PRODUCT-side, derive-from-
prompt, zero imports from tests/.

Every arm reads back what the engine actually composed (frames, SLOT
lines, directives) and returns a wire the stage's own whitelist parsers
accept — fixture, prompt, and script cannot drift because the script has
no other source. Content is deliberately plain: the CI flavor proves the
PIPELINE (routing, gates, trace, artifacts, receipts); drafting quality
is the live milestone's question, not this script's.
"""

import json
import re

_FRAME_RX = re.compile(
    r'<buyer_document source="([^"]+)"[^>]*>\n(.*?)\n</buyer_document>', re.S)
_LEAD_RX = re.compile(
    r'<pursuit_lead_context label="firm">\n(.*?)\n</pursuit_lead_context>', re.S)
_KB_CARD_RX = re.compile(
    r'<kb_card kb_id="([^"]+)" title="([^"]*)" label="firm">\n(.*?)\n</kb_card>', re.S)
_RESEARCH_FRAME_RX = re.compile(
    r'<external_research source="([^"]+)"[^>]*>\n(.*?)\n</external_research>', re.S)
_TOPICS_RX = re.compile(r"Abstracted research topics:\n((?:- [^\n]+\n?)+)")
_MODE_RX = re.compile(r"Research mode for this run: (\w+)\.")
_PACK_SECTION_RX = re.compile(
    r"## ([^\n]+)\n+source: (\S+)\n(.*?)(?=\n## |\Z)", re.S)
_FINDING_LINE_RX = re.compile(r"^- \((\w+)\) (\S+) \| (.*?): (.*)$", re.M)
_CANDIDATE_RX = re.compile(r"^(\d+)\. ", re.M)
_SLOT_RX = re.compile(r"^SLOT (\S+) \| ref (\S+)$", re.M)
_CANON_RX = re.compile(r"^CANONICAL (\S+): ", re.M)
_FLAG_SLOTS_RX = re.compile(r"^FLAGGED DRAFTING for slots: (.+?) — ", re.M)
_FLAG_SECTION_MARK = "FLAGGED DRAFTING for this section"
_SECTION_RX = re.compile(r"^SECTION: (.+)$", re.M)
_AUDIT_SLOT_RX = re.compile(
    r"SLOT (\S+) \| ref (\S+):\n(.*?)(?=\n\nSLOT |\n\nFACT SHEET CATALOG)", re.S)
_SUBQ_LINE_RX = re.compile(r"^\d+\. ", re.M)
_VAL_SECTION_RX = re.compile(r"^SECTION (\S+): ", re.M)


def _intake_analyst(prompt: str) -> str:
    content = " ".join(c for _s, c in _FRAME_RX.findall(prompt))
    wire: dict = {
        "buyer": {"name": "Northwind Regional Health", "vertical": "healthcare"},
        "procurement": {
            "what_is_bought": "ERP implementation services (finance, supply "
                              "chain, human capital management)",
            "response_structure": "designated",
        },
        "requirements": [],
        "red_flags": [],
    }
    terms = [t for t in ("data migration", "hypercare",
                         "organizational change management")
             if t in content.lower()]
    if terms:
        wire["buyer"]["terminology"] = terms
    lead = _LEAD_RX.search(prompt)
    if lead and "payroll" in lead.group(1).lower():
        wire["buyer"]["profile"] = ("Pursuit-lead context: transition risk is "
                                    "the buyer's stated fear; a failed payroll "
                                    "cutover is the named disaster.")
    return json.dumps(wire)


def _internal_researcher(prompt: str) -> str:
    topics = _TOPICS_RX.search(prompt)
    topic = (topics.group(1).strip().splitlines()[0][2:].strip()
             if topics else "buyer context")
    findings = [
        {"claim": f"Firm precedent: {body.strip().splitlines()[0].strip()}",
         "detail": title, "kb_id": kb_id, "topic": topic}
        for kb_id, title, body in _KB_CARD_RX.findall(prompt)
    ]
    return json.dumps({"findings": findings})


def _external_researcher(prompt: str) -> str:
    topics = _TOPICS_RX.search(prompt)
    topic = (topics.group(1).strip().splitlines()[0][2:].strip()
             if topics else "buyer context")
    findings = []
    frame = _RESEARCH_FRAME_RX.search(prompt)
    if frame:
        for heading, url, body in _PACK_SECTION_RX.findall(frame.group(2)):
            first = body.strip().replace("\n", " ").split(". ")[0]
            findings.append({"claim": first.rstrip(".") + ".",
                             "detail": heading, "source_url": url,
                             "topic": topic})
    return json.dumps({"findings": findings})


def _strategist(prompt: str) -> str:
    if prompt.startswith("Task: judge."):
        n = len(_CANDIDATE_RX.findall(prompt))
        return json.dumps({"verdicts": [
            {"candidate": i, "verdict": "keep"} if i <= 2 else
            {"candidate": i, "verdict": "kill",
             "reason": "weaker grounding than the kept pair"}
            for i in range(1, n + 1)]})
    found = _FINDING_LINE_RX.findall(prompt)
    candidates = []
    for i in range(min(4, max(2, len(found)))):
        _, source, _, claim = found[i % len(found)]
        candidates.append({
            "theme": f"Win theme {i + 1}: lead with {claim}",
            "rationale": f"grounded in {source}", "cites": [source]})
    return json.dumps({"candidates": candidates})


def _drafter(prompt: str) -> str:
    if prompt.startswith("Task: check."):
        return json.dumps({"verdict": "pass"})
    cards = _KB_CARD_RX.findall(prompt)
    kb_ids = [kb_id for kb_id, _t, _b in cards]
    bodies = {kb_id: body for kb_id, _t, body in cards}
    canon = _CANON_RX.findall(prompt)
    flagged = _FLAG_SLOTS_RX.search(prompt)
    flagged_slots = (set(s.strip() for s in flagged.group(1).split(","))
                     if flagged else set())
    flag_all = _FLAG_SECTION_MARK in prompt
    slots = _SLOT_RX.findall(prompt)
    answers = []
    for slot_id, ref in slots:
        prose = (f"Our approach to item {ref} follows the delivery record "
                 f"summarized in the framed material, stated plainly and "
                 f"scoped to what we operate today.")
        for kb_id in canon:
            if kb_id in bodies:
                prose += " " + " ".join(bodies[kb_id].split())
        if flag_all or slot_id in flagged_slots:
            prose += " [proposed approach]"
        answers.append({"slot_id": slot_id, "prose": prose,
                        "kb_ids": kb_ids[:2]})
    if not slots:  # Path B arm, unused by the Path-A demo but honest
        return json.dumps({"prose": "Section prose.", "kb_ids": kb_ids[:2]})
    return json.dumps({"answers": answers})


def _claim_auditor(prompt: str) -> str:
    rows = []
    for slot_id, _ref, prose in _AUDIT_SLOT_RX.findall(
            prompt + "\n\nFACT SHEET CATALOG"):
        head = prose.strip().split(". ")[0].strip()
        rows.append({"slot_id": slot_id,
                     "text": head if head.endswith(".") else head + ".",
                     "tier": 2, "fact_sheet_ref": None})
    return json.dumps({"claims": rows})


def _claim_verifier(prompt: str) -> str:
    return json.dumps({"verdict": "SUPPORTED",
                       "reasons": ["scripted CI arm — unused offline"]})


def _compliance(prompt: str) -> str:
    n = len(_SUBQ_LINE_RX.findall(prompt.split("ANSWER PROSE:")[0]))
    return json.dumps({"addressed": [{"index": i, "addressed": True}
                                     for i in range(n)]})


def _consistency(prompt: str) -> str:
    return json.dumps({"contradictions": []})


def _red_team(prompt: str) -> str:
    ids = _VAL_SECTION_RX.findall(prompt.split("THE DRAFT:")[-1])
    return json.dumps({
        "sections": [{"section_id": s, "score": 8, "weaknesses": []}
                     for s in ids],
        "ranked_fixes": ([{"rank": 1, "section_id": ids[0],
                           "fix": "lead with the transition-risk record"}]
                         if ids else [])})


def ci_script(*, fail_at_drafting_section: str | None = None) -> dict:
    """The full agent script. fail_at_drafting_section plants a kill (the
    resume test's lever — a real exception, no mocks)."""

    def drafter(prompt: str) -> str:
        if fail_at_drafting_section and not prompt.startswith("Task: check."):
            section = _SECTION_RX.search(prompt)
            if section and section.group(1) == fail_at_drafting_section:
                raise RuntimeError("scripted slice death (CI fixture)")
        return _drafter(prompt)

    return {
        "intake_analyst": _intake_analyst,
        "internal_researcher": _internal_researcher,
        "external_researcher": _external_researcher,
        "win_theme_strategist": _strategist,
        "section_drafter": drafter,
        "claim_auditor": _claim_auditor,
        "claim_verifier": _claim_verifier,
        "compliance_checker": _compliance,
        "consistency_checker": _consistency,
        "buyer_red_team": _red_team,
    }
