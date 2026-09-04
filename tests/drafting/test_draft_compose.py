"""compose.py: the prompt surfaces are exactly what B31 says they are —
right frame per trust level, buyer text never in the directive, and the
directive's pinned line formats (the derive-wire fixture's parse
targets) present.
"""

from engine.drafting.compose import (
    build_check_prompt,
    build_draft_prompt,
    dispositions_block,
    question_frame,
    section_directive,
)

SECTION = {"section_id": "1-delivery-approach", "title": "1. Delivery Approach"}

SLOT = {
    "slot_id": "s1", "ref_id": "1.1",
    "question_text": "Describe your delivery approach.",
    "sub_questions": ["What is the cutover plan?"],
    "constraints": {"max_words": 250, "brevity": "terse",
                    "flags": ["state_if_not_offered"]},
}

BRIEF = {
    "buyer": {"name": "Northwind Regional Health",
              "terminology": ["integrated ERP platform"]},
    "win_themes": {"approved": ["Win theme 1: lead with x"]},
}


class TestQuestionFrame:
    def test_buyer_text_is_s1_framed_with_sub_questions_inside(self):
        frame = question_frame(SLOT)
        assert '<buyer_document source="slot:s1" label="untrusted">' in frame
        assert "Describe your delivery approach." in frame
        assert "- What is the cutover plan?" in frame


class TestDirective:
    def _directive(self, **over):
        kwargs = dict(canonical_ids=[], flagged_slot_ids=[],
                      flag_section=False, path="A_designated")
        kwargs.update(over)
        return section_directive(SECTION, [SLOT], **kwargs)

    def test_slot_lines_and_constraint_instructions(self):
        directive = self._directive()
        assert "SLOT s1 | ref 1.1" in directive
        assert "hard limit: 250 words" in directive
        assert "be terse" in directive
        assert "state so plainly" in directive
        # Buyer text never enters the code-composed directive.
        assert "Describe your delivery approach" not in directive

    def test_canonical_and_flag_demands(self):
        directive = self._directive(canonical_ids=["kb_canon001"],
                                    flagged_slot_ids=["s1"])
        assert "CANONICAL kb_canon001:" in directive
        assert "FLAGGED DRAFTING for slots: s1" in directive
        assert "[proposed approach]" in directive

    def test_wire_reminder_names_the_exact_slot_ids(self):
        assert 'Return {"answers": [...]} with exactly these slot_ids: s1.' \
            in self._directive()

    def test_path_b_shape(self):
        section = dict(SECTION, requirement_refs=["r-001", "r-002"])
        directive = section_directive(section, [], canonical_ids=[],
                                      flagged_slot_ids=[], flag_section=True,
                                      path="B_free_flow")
        assert "Cover requirement refs: r-001, r-002" in directive
        assert "FLAGGED DRAFTING for this section" in directive
        assert 'Return {"prose": "...", "kb_ids": [...]}.' in directive


class TestDispositionsBlock:
    def test_firm_framed_with_both_kinds(self):
        block = dispositions_block([
            {"kind": "answered", "label": "gap_1", "text": "use this"},
            {"kind": "reframed", "label": "gap_2", "text": "go adjacent"},
        ])
        assert block.startswith('<pursuit_lead_context label="firm">')
        assert "gap_1: ANSWER PROVIDED — use this content: use this" in block
        assert "gap_2: REFRAME DIRECTION — go adjacent" in block


class TestPromptAssembly:
    def test_draft_prompt_order_and_frames(self):
        prompt = build_draft_prompt(
            voice_text="# Acme voice spec\n\n## Principles\n1. Clear.",
            frozen_brief=BRIEF, model_slots=[SLOT],
            card_frames=['<kb_card kb_id="kb_a" title="t" label="firm">\nb\n</kb_card>'],
            steering=[{"kind": "answered", "label": "g", "text": "x"}],
            directive="SECTION: 1. Delivery Approach")
        assert prompt.startswith("Task: draft.")
        assert '<voice_spec label="firm">' in prompt
        assert '<bid_brief_context label="semi_trusted">' in prompt
        assert "Buyer terminology: integrated ERP platform" in prompt
        assert '<buyer_document source="slot:s1"' in prompt
        assert '<kb_card kb_id="kb_a"' in prompt
        assert "<pursuit_lead_context" in prompt

    def test_notes_frame_sits_after_the_voice_spec(self):
        """P26c: steward-accepted notes ride the firm frame right after
        the voice spec; with none, the prompt is byte-identical."""
        kwargs = dict(
            voice_text="# Acme voice spec\n\n## Principles\n1. Clear.",
            frozen_brief=BRIEF, model_slots=[SLOT], card_frames=[],
            steering=[], directive="SECTION: 1. Delivery Approach")
        bare = build_draft_prompt(**kwargs)
        assert build_draft_prompt(**kwargs, notes_frame="") == bare
        prompt = build_draft_prompt(
            **kwargs, notes_frame='<steward_notes label="firm">\n- [playbook] '
                                  'Lead with the outcome.\n</steward_notes>')
        assert prompt.index("</voice_spec>") < prompt.index("<steward_notes") \
            < prompt.index("<bid_brief_context")
        assert "- [playbook] Lead with the outcome." in prompt

    def test_check_prompt_shape(self):
        prompt = build_check_prompt(
            SECTION, {"s1": {"prose": "the drafted answer"}},
            checklist=["hard limit: 250 words"], path="A_designated")
        assert prompt.startswith("Task: check.")
        assert "SLOT s1:" in prompt
        assert "the drafted answer" in prompt
        assert "- hard limit: 250 words" in prompt
        assert '"verdict": "fixed"' in prompt
