"""Coverage + consistency units (B34(7,8)): every rule recomputed from
prose + slot container, every positive with its planted negative, length
on delivered text with markers stripped."""

from engine.drafting.verify import PROPOSED_FLAG
from engine.validation import (
    build_consistency_prompt,
    build_subq_prompt,
    coverage_findings,
    cross_ref_findings,
    delivered_text,
    parse_consistency_wire,
    parse_subq_wire,
)


def _slot(slot_id="sl_1", ref="1.0.1", **over):
    slot = {"slot_id": slot_id, "ref_id": ref, "constraints": {}}
    slot.update(over)
    return slot


def _answer(slot_id="sl_1", ref="1.0.1", status="drafted", prose="Fine answer.",
            **over):
    answer = {"slot_id": slot_id, "ref_id": ref, "status": status,
              "prose": prose}
    answer.update(over)
    return answer


def _section(answers, section_id="s1", **over):
    section = {"section_id": section_id, "section_type": "other",
               "status": "drafted", "answers": answers}
    section.update(over)
    return section


def _ids(findings):
    return [f.finding_id for f in findings]


def test_delivered_text_strips_the_review_marker():
    prose = f"Real words {PROPOSED_FLAG} more words"
    assert PROPOSED_FLAG not in delivered_text(prose)
    assert "Real words" in delivered_text(prose)


def test_length_measured_on_delivered_text_pair():
    # 5 real words + the 2-word marker: a naive count of 7 would flag; the
    # delivered count of 5 must not (the v1 lesson, non-vacuous both ways).
    slot = _slot(constraints={"max_words": 5})
    prose = f"one two three four five {PROPOSED_FLAG}"
    clean = coverage_findings(_section([_answer(prose=prose)]),
                              {"sl_1": slot})
    assert clean == []
    over = coverage_findings(
        _section([_answer(prose="one two three four five six")]),
        {"sl_1": slot})
    assert _ids(over) == ["coverage:length_exceeded:s1:sl_1"]
    assert "delivered text" in over[0].message


def test_pending_slot_is_a_review_finding():
    findings = coverage_findings(
        _section([_answer(status="pending", prose="", reason="wire failed")]),
        {"sl_1": _slot()})
    assert _ids(findings) == ["coverage:slot_unanswered:s1:sl_1"]
    assert "wire failed" in findings[0].message


def test_flag_demand_recomputed_from_prose_pair():
    flagged = frozenset({"sl_1"})
    missing = coverage_findings(
        _section([_answer(prose="No flag here.")]), {"sl_1": _slot()},
        flagged_slots=flagged)
    assert _ids(missing) == ["coverage:flag_missing:s1:sl_1"]
    present = coverage_findings(
        _section([_answer(prose=f"Bold idea {PROPOSED_FLAG}.")]),
        {"sl_1": _slot()}, flagged_slots=flagged)
    assert present == []


def test_omission_line_recomputed_pair():
    slot = _slot(question_text="Provide quantum telemetry evidence.",
                 constraints={"flags": ["state_if_not_offered"]})
    honest = ("Not offered: Provide quantum telemetry evidence. We state "
              "capability boundaries plainly rather than overstate scope.")
    clean = coverage_findings(
        _section([_answer(status="omitted", prose=honest)]), {"sl_1": slot})
    assert clean == []
    softened = coverage_findings(
        _section([_answer(status="omitted",
                          prose="We could explore this in the future.")]),
        {"sl_1": slot})
    assert _ids(softened) == ["coverage:omission_line_missing:s1:sl_1"]


def test_constraint_obligations_get_review_findings():
    slot = _slot(constraints={"flags": ["disclose_partner_delivery",
                                        "no_offshore"]})
    findings = coverage_findings(_section([_answer()]), {"sl_1": slot})
    assert len(findings) == 2
    assert all(f.rule == "constraint_review" for f in findings)
    messages = " ".join(f.message for f in findings)
    assert "disclose_partner_delivery" in messages
    assert "no_offshore" in messages


def test_canonical_recomputed_pair():
    body = "Our training program prepares staff before go-live."
    drafted = _section([_answer(prose=f"Intro. {body} Outro.")],
                       canonical=[{"kb_id": "kb_c", "verified": True}])
    assert coverage_findings(drafted, {"sl_1": _slot()},
                             canonical_bodies={"kb_c": body}) == []
    violated = _section([_answer(prose="Paraphrased training words.")],
                        canonical=[{"kb_id": "kb_c", "verified": True}])
    findings = coverage_findings(violated, {"sl_1": _slot()},
                                 canonical_bodies={"kb_c": body})
    assert _ids(findings) == ["coverage:canonical_violated:s1"]


def test_subq_prompt_and_wire_pair():
    prompt = build_subq_prompt("4. Testing", "Describe UAT.",
                               ["How are defects triaged?",
                                "How are exit criteria set?"], "Prose.")
    assert prompt.startswith("Task: check sub-questions.")
    assert "0. How are defects triaged?" in prompt
    ok = parse_subq_wire('{"addressed": [{"index": 0, "addressed": true}, '
                         '{"index": 1, "addressed": true}]}',
                         section_id="s4", slot_id="sl_2", n=2)
    assert ok == []
    missed = parse_subq_wire('{"addressed": [{"index": 0, "addressed": true}, '
                             '{"index": 1, "addressed": false}]}',
                             section_id="s4", slot_id="sl_2", n=2)
    assert _ids(missed) == ["coverage:sub_question_unaddressed:s4:sl_2"]
    assert "sub-question 1" in missed[0].message


def test_subq_unparseable_is_not_a_pass():
    findings = parse_subq_wire("garbage", section_id="s4", slot_id="sl_2", n=2)
    assert _ids(findings) == ["coverage:sub_question_unaddressed:s4:sl_2"]
    assert "not a pass" in findings[0].message


def test_subq_and_consistency_scalar_json_never_crash():
    # `null` decodes to a non-object (live-model behavior, P8): both
    # parsers must take their unparseable lane, not raise TypeError.
    findings = parse_subq_wire("null", section_id="s4", slot_id="sl_2", n=2)
    assert _ids(findings) == ["coverage:sub_question_unaddressed:s4:sl_2"]
    none_found, warnings = parse_consistency_wire(
        "null", known_ids=frozenset({"s1", "s2"}))
    assert none_found == []
    assert any("unparseable" in w for w in warnings)


def test_cross_ref_dangling_pair():
    slots = {
        "sl_1": _slot("sl_1", "2.0.3", cross_refs=["4.0.1"]),
        "sl_2": _slot("sl_2", "4.0.1"),
    }
    healthy = cross_ref_findings(
        [_section([_answer("sl_1", "2.0.3")], section_id="s2"),
         _section([_answer("sl_2", "4.0.1")], section_id="s4")], slots)
    assert healthy == []
    dangling = cross_ref_findings(
        [_section([_answer("sl_1", "2.0.3")], section_id="s2"),
         _section([_answer("sl_2", "4.0.1", status="pending", prose="")],
                  section_id="s4")], slots)
    assert _ids(dangling) == ["consistency:cross_ref_dangling:s2:sl_1"]
    assert "4.0.1" in dangling[0].message and "pending" in dangling[0].message


def test_consistency_wire_whitelists_and_flags_both_sections():
    prompt = build_consistency_prompt([("s1", "One", "P1"), ("s2", "Two", "P2")])
    assert prompt.startswith("Task: check consistency.")
    findings, warnings = parse_consistency_wire(
        '{"contradictions": [{"section_ids": ["s1", "s2"], "detail": "d"}, '
        '{"section_ids": ["s1", "ghost"], "detail": "x"}]}',
        known_ids=frozenset({"s1", "s2"}))
    assert sorted(_ids(findings)) == ["consistency:contradiction:s1",
                                      "consistency:contradiction:s2"]
    assert any("unknown section ids" in w for w in warnings)
    none_found, warnings2 = parse_consistency_wire(
        '{"contradictions": []}', known_ids=frozenset({"s1"}))
    assert none_found == [] and warnings2 == []
