"""wire.py: whitelist parse, reconcile-by-slot_id, the citation gate,
and the draft-pends / check-fails-open asymmetry (B31(2)).

v1 harvest lineage per test is noted where it applies
(the v1 repo's tests/test_drafter.py, read-only oracle).
"""

import json

import pytest

from engine.drafting.wire import (
    WireError,
    parse_wire_answers,
    parse_wire_check,
    parse_wire_prose,
)

OPENED = {"kb_a", "kb_b"}


def _wire(entries):
    return json.dumps({"answers": entries})


class TestParseAnswers:
    def test_reconcile_by_slot_id_not_position(self):
        # v1: order untrusted — reversed wire still keys correctly.
        text = _wire([
            {"slot_id": "s2", "prose": "two", "kb_ids": ["kb_b"]},
            {"slot_id": "s1", "prose": "one", "kb_ids": ["kb_a"]},
        ])
        answers, warnings = parse_wire_answers(
            text, requested=["s1", "s2"], opened_ids=OPENED)
        assert answers["s1"]["prose"] == "one"
        assert answers["s2"]["prose"] == "two"
        assert warnings == []

    def test_missing_slot_is_absent_for_the_caller_to_pend(self):
        # v1: a missing slot pends with the resume command on it.
        answers, _ = parse_wire_answers(
            _wire([{"slot_id": "s1", "prose": "one"}]),
            requested=["s1", "s2"], opened_ids=OPENED)
        assert "s2" not in answers

    def test_unrequested_and_duplicate_dropped_and_reported(self):
        text = _wire([
            {"slot_id": "s1", "prose": "one"},
            {"slot_id": "s1", "prose": "one again"},
            {"slot_id": "s9", "prose": "never asked"},
        ])
        answers, warnings = parse_wire_answers(
            text, requested=["s1"], opened_ids=OPENED)
        assert answers["s1"]["prose"] == "one"
        assert len(answers) == 1
        assert any("duplicate" in w for w in warnings)
        assert any("not requested" in w or "was not" in w for w in warnings)

    def test_nonprose_slots_are_never_requested_so_the_wire_has_no_arm(self):
        # v1: the model structurally cannot emit records/pricing — here the
        # requested list excludes shape-skipped slots, so an answer for one
        # is unrequested-and-dropped, never kept.
        text = _wire([{"slot_id": "pricing_grid_slot", "prose": "$1,000,000"}])
        answers, warnings = parse_wire_answers(
            text, requested=["s1"], opened_ids=OPENED)
        assert answers == {}
        assert len(warnings) == 1

    def test_malformed_entries_dropped_and_reported(self):
        text = _wire([
            "not a dict",
            {"prose": "no slot id"},
            {"slot_id": "s1"},          # no prose
            {"slot_id": "s2", "prose": "fine"},
        ])
        answers, warnings = parse_wire_answers(
            text, requested=["s1", "s2"], opened_ids=OPENED)
        assert list(answers) == ["s2"]
        assert len(warnings) == 3

    def test_cite_outside_section_selection_dropped(self):
        # The RAG ban's teeth (B31(1), v1 validate_planned_citations):
        # kb_x was never opened for this section — removed, reported,
        # never reaches cards_cited.
        text = _wire([{"slot_id": "s1", "prose": "p",
                       "kb_ids": ["kb_a", "kb_x", "kb_a"]}])
        answers, warnings = parse_wire_answers(
            text, requested=["s1"], opened_ids=OPENED)
        assert answers["s1"]["kb_ids"] == ["kb_a"]  # deduped, kb_x gone
        assert any("kb_x" in w for w in warnings)

    def test_unparseable_wire_raises_for_the_caller_to_pend(self):
        with pytest.raises(WireError):
            parse_wire_answers("not json", requested=["s1"], opened_ids=OPENED)
        with pytest.raises(WireError):
            parse_wire_answers(json.dumps({"no": "answers"}),
                               requested=["s1"], opened_ids=OPENED)


class TestParseProse:
    def test_prose_arm(self):
        out, warnings = parse_wire_prose(
            json.dumps({"prose": "text", "kb_ids": ["kb_a", "kb_x"]}),
            opened_ids=OPENED)
        assert out["prose"] == "text"
        assert out["kb_ids"] == ["kb_a"]
        assert len(warnings) == 1

    def test_missing_prose_raises(self):
        with pytest.raises(WireError):
            parse_wire_prose(json.dumps({"kb_ids": []}), opened_ids=OPENED)


class TestParseCheck:
    def test_pass_verdict(self):
        assert parse_wire_check(json.dumps({"verdict": "pass"}),
                                requested=["s1"], opened_ids=OPENED) \
            == ("pass", None, [])

    def test_fixed_returns_replacement(self):
        text = json.dumps({"verdict": "fixed", "answers": [
            {"slot_id": "s1", "prose": "better", "kb_ids": ["kb_a"]}]})
        verdict, replacement, warnings = parse_wire_check(
            text, requested=["s1"], opened_ids=OPENED)
        assert verdict == "fixed"
        assert replacement["s1"]["prose"] == "better"

    def test_fixed_prose_arm(self):
        text = json.dumps({"verdict": "fixed", "prose": "better", "kb_ids": []})
        verdict, replacement, _ = parse_wire_check(
            text, requested=None, opened_ids=OPENED)
        assert verdict == "fixed"
        assert replacement["prose"] == "better"

    def test_unparseable_check_fails_open(self):
        # B31(2): the check is an improver, never a destroyer.
        verdict, replacement, warnings = parse_wire_check(
            "garbage", requested=["s1"], opened_ids=OPENED)
        assert (verdict, replacement) == ("pass", None)
        assert any("draft kept" in w for w in warnings)

    def test_unknown_verdict_fails_open(self):
        verdict, _, warnings = parse_wire_check(
            json.dumps({"verdict": "maybe"}), requested=["s1"],
            opened_ids=OPENED)
        assert verdict == "pass"
        assert warnings

    def test_malformed_fix_fails_open(self):
        text = json.dumps({"verdict": "fixed"})  # no answers/prose
        verdict, replacement, warnings = parse_wire_check(
            text, requested=["s1"], opened_ids=OPENED)
        assert (verdict, replacement) == ("pass", None)
        assert any("draft kept" in w for w in warnings)
