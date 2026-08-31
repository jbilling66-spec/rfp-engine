"""route.py: the gap->slot join, per-disposition lanes, gating at draft
time, and the section_type assigner.

Gap pings are built with the REAL compose_ping — the matcher's format
assumption and the mapper's format cannot drift apart silently.
"""

import pytest

from engine.drafting.route import (
    AWAITING,
    GATED,
    MODEL,
    OMITTED,
    SECTION_KEYWORDS,
    SHAPE,
    assign_section_type,
    section_plan,
)
from engine.kb.ingest import SECTION_TYPES
from engine.planning.mapper import compose_ping

TITLE = "2. Special Requirements"


def _slot(slot_id, *, ref_id=None, shape="prose", gates=None, flags=None,
          max_words=None):
    slot = {"slot_id": slot_id, "response_shape": shape}
    if ref_id:
        slot["ref_id"] = ref_id
    if gates:
        slot["gating"] = {"gates": gates}
    constraints = {}
    if flags:
        constraints["flags"] = flags
    if max_words is not None:
        constraints["max_words"] = max_words
    if constraints:
        slot["constraints"] = constraints
    return slot


def _gap(slot, status, **extra):
    gap = {
        "gap_id": f"gap_{slot['slot_id']}",
        "slot_id": slot["slot_id"],  # the structural join (E1)
        "kind": "no_content",
        "question_to_human": compose_ping(
            TITLE, slot.get("ref_id") or slot["slot_id"], "the ask?"),
        "status": status,
    }
    gap.update(extra)
    return gap


def _section(slots, gaps=()):
    return {
        "section_id": "2-special-requirements",
        "title": TITLE,
        "slot_ids": [s["slot_id"] for s in slots],
        "gaps": list(gaps),
    }


class TestLanesPathA:
    def test_default_lanes_model_and_shape(self):
        slots = [_slot("s1"), _slot("s2", shape="boolean")]
        by_id = {s["slot_id"]: s for s in slots}
        plan = section_plan(_section(slots), by_id, "A_designated")
        lanes = {l["slot_id"]: l["lane"] for l in plan["lanes"]}
        assert lanes == {"s1": MODEL, "s2": SHAPE}
        assert plan["status"] == MODEL
        assert plan["warnings"] == []

    def test_omit_approved_slot_omitted_with_note(self):
        slots = [_slot("s1", ref_id="2.1"), _slot("s2", ref_id="2.2")]
        by_id = {s["slot_id"]: s for s in slots}
        section = _section(slots, [_gap(slots[0], "omit_approved",
                                        note="out of scope this cycle")])
        plan = section_plan(section, by_id, "A_designated")
        lane = plan["lanes"][0]
        assert lane["lane"] == OMITTED
        assert lane["reason"] == "out of scope this cycle"
        assert plan["status"] == MODEL  # s2 still drafts

    def test_open_gap_slot_awaits_without_spend(self):
        slots = [_slot("s1", ref_id="2.1"), _slot("s2", ref_id="2.2")]
        by_id = {s["slot_id"]: s for s in slots}
        section = _section(slots, [_gap(slots[0], "open")])
        plan = section_plan(section, by_id, "A_designated")
        assert plan["lanes"][0]["lane"] == AWAITING
        assert "invention" in plan["lanes"][0]["reason"]

    def test_answered_and_reframed_become_steering_not_lane_changes(self):
        slots = [_slot("s1", ref_id="2.1"), _slot("s2", ref_id="2.2")]
        by_id = {s["slot_id"]: s for s in slots}
        section = _section(slots, [
            _gap(slots[0], "answered", answer="We hold ISO 27001."),
            _gap(slots[1], "reframed",
                 reframe={"note": "lead with the adjacent managed-service "
                                  "strength", "mandatory_review": True}),
        ])
        plan = section_plan(section, by_id, "A_designated")
        assert all(l["lane"] == MODEL for l in plan["lanes"])
        kinds = {s["kind"]: s["text"] for s in plan["steering"]}
        assert kinds["answered"] == "We hold ISO 27001."
        assert "managed-service" in kinds["reframed"]

    def test_draft_flagged_marks_the_slot(self):
        slots = [_slot("s1", ref_id="2.1")]
        by_id = {s["slot_id"]: s for s in slots}
        section = _section(slots, [_gap(slots[0], "draft_flagged")])
        plan = section_plan(section, by_id, "A_designated")
        assert plan["lanes"][0]["lane"] == MODEL
        assert plan["lanes"][0]["flagged"] is True

    def test_gated_children_stay_gated_even_when_gap_answered(self):
        gater = _slot("s1", ref_id="2.1", gates=["s2"])
        child = _slot("s2", ref_id="2.2")
        by_id = {"s1": gater, "s2": child}
        section = _section([gater, child],
                           [_gap(gater, "answered", answer="Yes we do.")])
        plan = section_plan(section, by_id, "A_designated")
        lanes = {l["slot_id"]: l["lane"] for l in plan["lanes"]}
        assert lanes["s2"] == GATED  # answer routes to the GATER's draft only

    def test_all_shape_skipped_section(self):
        slots = [_slot("s1", shape="record"), _slot("s2", shape="numeric")]
        by_id = {s["slot_id"]: s for s in slots}
        plan = section_plan(_section(slots), by_id, "A_designated")
        assert plan["status"] == SHAPE

    def test_all_omitted_section(self):
        slots = [_slot("s1", ref_id="2.1")]
        by_id = {s["slot_id"]: s for s in slots}
        section = _section(slots, [_gap(slots[0], "omit_approved")])
        plan = section_plan(section, by_id, "A_designated")
        assert plan["status"] == OMITTED


class TestUnmatchedGapDegradation:
    def _unmatched(self, status, **extra):
        gap = {"gap_id": "gap_x", "kind": "no_content", "status": status,
               "question_to_human": "[Elsewhere / 9] the ask?\nx"}
        gap.update(extra)
        return gap

    def test_unmatched_omit_pends_the_whole_section(self):
        slots = [_slot("s1", ref_id="2.1")]
        by_id = {s["slot_id"]: s for s in slots}
        section = _section(slots, [self._unmatched("omit_approved")])
        plan = section_plan(section, by_id, "A_designated")
        assert plan["status"] == AWAITING
        assert "will not guess" in plan["reason"]
        assert any("carries no slot_id" in w for w in plan["warnings"])

    def test_misreferenced_slot_id_degrades_like_no_slot_id(self):
        # A slot_id outside this section is plan corruption, not a target:
        # same refusal-to-guess as a slot-less gap.
        slots = [_slot("s1", ref_id="2.1")]
        by_id = {s["slot_id"]: s for s in slots}
        gap = self._unmatched("omit_approved")
        gap["slot_id"] = "s99"
        plan = section_plan(_section(slots, [gap]), by_id, "A_designated")
        assert plan["status"] == AWAITING
        assert any("not a slot of" in w for w in plan["warnings"])

    def test_unmatched_open_pends_the_whole_section(self):
        slots = [_slot("s1", ref_id="2.1")]
        by_id = {s["slot_id"]: s for s in slots}
        section = _section(slots, [self._unmatched("open")])
        assert section_plan(section, by_id, "A_designated")["status"] == AWAITING

    def test_unmatched_additive_dispositions_degrade_to_section_scope(self):
        slots = [_slot("s1", ref_id="2.1")]
        by_id = {s["slot_id"]: s for s in slots}
        section = _section(slots, [
            self._unmatched("answered", answer="content"),
            self._unmatched("draft_flagged"),
        ])
        plan = section_plan(section, by_id, "A_designated")
        assert plan["status"] == MODEL  # additive — drafting proceeds
        assert plan["flag_section"] is True
        assert any(s["kind"] == "answered" for s in plan["steering"])


class TestPathB:
    def test_omit_approved_is_whole_section_omission(self):
        section = {"section_id": "x", "title": "X", "gaps": [
            {"status": "omit_approved", "note": "buyer covers this"}]}
        plan = section_plan(section, {}, "B_free_flow")
        assert plan["status"] == OMITTED
        assert plan["reason"] == "buyer covers this"

    def test_open_gap_pends_the_section(self):
        section = {"section_id": "x", "title": "X",
                   "gaps": [{"status": "open", "gap_id": "g1"}]}
        assert section_plan(section, {}, "B_free_flow")["status"] == AWAITING

    def test_answered_steers_and_flagged_flags(self):
        section = {"section_id": "x", "title": "X", "gaps": [
            {"status": "answered", "answer": "use this", "gap_id": "g1"},
            {"status": "draft_flagged", "gap_id": "g2"}]}
        plan = section_plan(section, {}, "B_free_flow")
        assert plan["status"] == MODEL
        assert plan["flag_section"] is True
        assert plan["steering"][0]["text"] == "use this"


class TestSectionType:
    def test_vocabulary_table_is_subset_of_ingest_source(self):
        assert {t for t, _ in SECTION_KEYWORDS} <= SECTION_TYPES

    @pytest.mark.parametrize("title,expected", [
        ("Executive Summary", "exec_summary"),
        ("1. Delivery Approach", "methodology"),
        ("Data Migration Strategy", "data_migration"),
        ("Pricing", "pricing_narrative"),
        ("Project Team and Staffing", "staffing"),
        ("Security & Compliance", "security_compliance"),
    ])
    def test_titles_assign_deterministically(self, title, expected):
        assert assign_section_type(title, []) == expected

    def test_slot_text_participates(self):
        assert assign_section_type(
            "Section 4", ["Describe your data migration methodology"],
        ) == "data_migration"

    def test_no_keyword_falls_back_to_other(self):
        assert assign_section_type(
            "Quantum Blockchain Telemetry", ["ledger attestations"],
        ) == "other"

    def test_substring_does_not_false_match(self):
        # "migration" must not fire inside "immigration" — word-boundary
        # matching, not raw substring.
        assert assign_section_type("Immigration policy overview", []) == "other"
