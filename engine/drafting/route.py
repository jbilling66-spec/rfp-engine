"""Draft-time lanes: which slots the model drafts, which code handles,
and which pend — the plan's Gate-2 dispositions read back (B24/B31).

The gap->slot join is STRUCTURAL since P9/E1 (B31(11) closed): plan
gaps carry slot_id, written by the mapper. The matcher that recovered
slot identity from the ping text is deleted. The degradation contract
is unchanged — when a gap carries no slot_id (section-scoped) or a
slot_id outside this section (plan corruption), the engine refuses to
guess: additive dispositions (answered / reframed / draft_flagged)
degrade to section-scope steering, but an untargetable omission or open
gap pends the WHOLE section loudly — drafting content a human approved
omitting, or into a gap nobody grounded, would be invention.

Gating at draft time: children of a gap-carrying gater stay gated
skipped regardless of the gap's disposition — an answered gate question
routes its answer to the GATER's draft; interpreting the answer to
unlock children would be invention (P9 revision owns unlocking).

section_type (B31(5)): deterministic keyword assigner over the KB
ingest SECTION_TYPES vocabulary (the single source; A2 revises it) +
"other". Pure, corpus-free, first match wins.
"""

import re

from engine.kb.ingest import SECTION_TYPES
from engine.planning.sections import cascade_gating, is_answerable

MODEL = "model"
OMITTED = "omitted"
GATED = "gated_skipped"
SHAPE = "shape_skipped"
AWAITING = "awaiting_disposition"

# Ordered: more specific families before broad ones ("approach" alone
# would swallow integration/data-migration sections). First match wins.
SECTION_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("exec_summary", ("executive summary", "executive overview")),
    ("company_overview", ("company overview", "company profile", "about us",
                          "firm overview", "who we are")),
    ("past_performance", ("past performance", "relevant experience",
                          "qualifications", "case studies")),
    ("references", ("references", "client references")),
    ("data_migration", ("data migration", "data conversion", "migration")),
    ("integration_approach", ("integration", "interfaces")),
    ("security_compliance", ("security", "compliance", "privacy")),
    ("pricing_narrative", ("pricing", "fees", "cost", "rates", "commercial")),
    ("staffing", ("staffing", "key personnel", "project team", "resources")),
    ("timeline", ("timeline", "schedule", "milestones", "work plan")),
    ("testing", ("testing", "test strategy", "quality assurance")),
    ("training", ("training", "enablement", "knowledge transfer")),
    ("support_model", ("support", "hypercare", "maintenance", "warranty")),
    ("governance", ("governance", "steering", "escalation")),
    ("reporting", ("reporting", "dashboards", "status reports")),
    ("methodology", ("methodology", "approach", "delivery", "implementation")),
)

_NORM = re.compile(r"[^a-z0-9]+")

# The table cannot drift from its vocabulary source: checked at import.
_UNKNOWN = {t for t, _ in SECTION_KEYWORDS} - SECTION_TYPES
if _UNKNOWN:
    raise RuntimeError(f"SECTION_KEYWORDS outside SECTION_TYPES: {_UNKNOWN}")


def _haystack(parts: list[str]) -> str:
    return " " + _NORM.sub(" ", " ".join(parts).lower()).strip() + " "


def assign_section_type(title: str, texts: list[str]) -> str:
    """First SECTION_TYPES value whose keyword appears in title+texts;
    'other' fallback."""
    hay = _haystack([title, *texts])
    for section_type, keywords in SECTION_KEYWORDS:
        for keyword in keywords:
            if f" {_NORM.sub(' ', keyword)} " in hay:
                return section_type
    return "other"


def section_plan(section: dict, slots_by_id: dict, path: str) -> dict:
    """The section's complete draft-time routing: per-slot lanes (Path A),
    section status, steering for the prompt, and every degradation named.

    Returns {status, reason, lanes, steering, flag_section, warnings}
    where status is one of model | omitted | awaiting_disposition |
    skipped_non_prose, lanes is [{slot_id, lane, reason?, gap?,
    flagged?}] (Path A only, plan slot order), and steering is
    [{kind, label, text}] for the dispositions block."""
    warnings: list[str] = []
    steering: list[dict] = []
    flag_section = False

    if path != "A_designated":
        return _section_plan_b(section, steering, warnings)

    lanes: dict[str, dict] = {}
    for slot_id in section.get("slot_ids", []):
        slot = slots_by_id[slot_id]
        if is_answerable(slot):
            lanes[slot_id] = {"slot_id": slot_id, "lane": MODEL}
        else:
            lanes[slot_id] = {"slot_id": slot_id, "lane": SHAPE,
                              "reason": "no authored-prose lane at P7 (B28(4))"}

    section_pend: str | None = None
    matched_gap_slots: set[str] = set()
    for gap in section.get("gaps", []):
        status = gap.get("status")
        slot_id = gap.get("slot_id")
        if slot_id is not None and slot_id not in lanes:
            warnings.append(
                f"gap {_gap_label(gap, None)}: slot_id {slot_id!r} is not a "
                f"slot of {section['section_id']} — disposition degrades to "
                "section scope")
            slot_id = None
        label = _gap_label(gap, slot_id)
        if slot_id is not None:
            matched_gap_slots.add(slot_id)
            lane = lanes.get(slot_id)
            if lane is None or lane["lane"] != MODEL:
                warnings.append(
                    f"gap {label} matched non-model slot {slot_id}; ignored")
                continue
            if status == "omit_approved":
                lane["lane"] = OMITTED
                lane["reason"] = gap.get("note") or "omission approved (B24)"
                lane["gap"] = gap
            elif status in ("open", "pinged"):
                lane["lane"] = AWAITING
                lane["reason"] = (f"gap {label} undisposed ({status}) — "
                                  "drafting into it would be invention")
                lane["gap"] = gap
            elif status == "answered":
                lane["gap"] = gap
                steering.append({"kind": "answered", "label": label,
                                 "text": gap.get("answer", "")})
            elif status == "reframed":
                lane["gap"] = gap
                steering.append({
                    "kind": "reframed", "label": label,
                    "text": gap.get("reframe", {}).get("note", "")})
            elif status == "draft_flagged":
                lane["gap"] = gap
                lane["flagged"] = True
            else:
                warnings.append(f"gap {label}: unknown status {status!r}; "
                                "treated as undisposed")
                lane["lane"] = AWAITING
                lane["reason"] = f"gap {label} carries unknown status"
        else:
            warnings.append(
                f"gap {label} carries no slot_id in {section['section_id']} "
                "— disposition degrades to section scope")
            if status == "answered":
                steering.append({"kind": "answered", "label": label,
                                 "text": gap.get("answer", "")})
            elif status == "reframed":
                steering.append({
                    "kind": "reframed", "label": label,
                    "text": gap.get("reframe", {}).get("note", "")})
            elif status == "draft_flagged":
                flag_section = True
            else:  # omit_approved / open / pinged — untargetable, refuse to guess
                section_pend = (
                    f"gap {label} ({status}) could not be matched to a slot; "
                    "the engine will not guess which content the disposition "
                    "governs — human review needed")

    # Children of a gap-carrying gater stay gated regardless of disposition.
    section_slots = [slots_by_id[sid] for sid in section.get("slot_ids", [])]
    for slot_id in cascade_gating(section_slots, matched_gap_slots):
        lane = lanes.get(slot_id)
        if lane is not None and lane["lane"] == MODEL:
            lane["lane"] = GATED
            lane["reason"] = ("gated by a slot whose gap rode to Gate 2 — "
                              "the drafter cannot know the gate's answer")

    lane_list = [lanes[sid] for sid in section.get("slot_ids", [])]
    model_lanes = [l for l in lane_list if l["lane"] == MODEL]
    answerable = [l for l in lane_list if l["lane"] != SHAPE]

    if section_pend is not None:
        status, reason = AWAITING, section_pend
    elif not answerable:
        status, reason = SHAPE, "no authored-prose lane at P7 (B28(4))"
    elif model_lanes:
        status, reason = MODEL, None
    elif all(l["lane"] == OMITTED for l in answerable):
        status, reason = OMITTED, "every answerable slot's omission approved"
    else:
        status, reason = AWAITING, "no slot is draftable"

    return {"status": status, "reason": reason, "lanes": lane_list,
            "steering": steering, "flag_section": flag_section,
            "warnings": warnings}


def _section_plan_b(section: dict, steering: list, warnings: list) -> dict:
    """Path B: gaps are section-scoped by construction (outline.py)."""
    status, reason, flag_section = MODEL, None, False
    for gap in section.get("gaps", []):
        gstatus = gap.get("status")
        label = _gap_label(gap, None)
        if gstatus == "omit_approved":
            status = OMITTED
            reason = gap.get("note") or "omission approved (B24)"
        elif gstatus in ("open", "pinged"):
            status = AWAITING
            reason = (f"gap {label} undisposed ({gstatus}) — drafting into "
                      "it would be invention")
        elif gstatus == "answered":
            steering.append({"kind": "answered", "label": label,
                             "text": gap.get("answer", "")})
        elif gstatus == "reframed":
            steering.append({"kind": "reframed", "label": label,
                             "text": gap.get("reframe", {}).get("note", "")})
        elif gstatus == "draft_flagged":
            flag_section = True
        else:
            warnings.append(f"gap {label}: unknown status {gstatus!r}; "
                            "section pends")
            status, reason = AWAITING, f"gap {label} carries unknown status"
    return {"status": status, "reason": reason, "lanes": [],
            "steering": steering, "flag_section": flag_section,
            "warnings": warnings}


def _gap_label(gap: dict, slot_id: str | None) -> str:
    return gap.get("gap_id") or slot_id or "(unnumbered)"
