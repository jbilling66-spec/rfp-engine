"""verify.py + the voice-spec loader: every envelope claim about draft
text is code-scanned, the honest-omission line is code-composed and
buyer-instructed only, length checks warn (P8 enforces — B31(14)).

Non-vacuity discipline: every positive assertion has its negative pair
in the same class (flag present/absent, within/over limit, verbatim/
altered) so no check could pass by never firing.
"""

import pytest

from engine.drafting.compose import (
    VOICE_DEFAULT,
    VoiceSpecError,
    load_voice_spec,
)
from engine.drafting.verify import (
    PROPOSED_FLAG,
    canonical_verified,
    flag_present,
    length_warnings,
    normalize_ws,
    omission_line,
)

CANON = "We deliver ERP cutovers with a rehearsed, evidence-backed runbook."


class TestCanonical:
    def test_whitespace_variation_still_verifies(self):
        text = ("Intro sentence. We deliver ERP cutovers   with a\n"
                "rehearsed, evidence-backed runbook. Outro.")
        assert canonical_verified(CANON, text)

    def test_altered_body_fails(self):
        assert not canonical_verified(
            CANON, "We deliver ERP cutovers with an improvised runbook.")

    def test_normalize_ws(self):
        assert normalize_ws("a\n b\t c ") == "a b c"


class TestFlag:
    def test_present_and_absent(self):
        assert flag_present(f"We propose X. {PROPOSED_FLAG}")
        assert not flag_present("We propose X.")


class TestOmissionLine:
    def test_composed_only_when_buyer_instructed(self):
        slot = {"slot_id": "s1", "question_text": "Do you offer 24/7 SOC?",
                "constraints": {"flags": ["state_if_not_offered"]}}
        line = omission_line(slot)
        assert line == ("Not offered: Do you offer 24/7 SOC. We state "
                        "capability boundaries plainly rather than "
                        "overstate scope.")

    def test_absent_flag_composes_nothing(self):
        slot = {"slot_id": "s1", "question_text": "Do you offer 24/7 SOC?",
                "constraints": {"flags": ["no_offshore"]}}
        assert omission_line(slot) is None

    def test_no_constraints_at_all(self):
        assert omission_line({"slot_id": "s1", "question_text": "Q?"}) is None


class TestLengthWarnings:
    def test_over_word_limit_warns(self):
        slot = {"slot_id": "s1", "constraints": {"max_words": 3}}
        warnings = length_warnings(slot, "one two three four")
        assert len(warnings) == 1
        assert "max_words 3" in warnings[0]

    def test_within_limit_is_silent(self):
        slot = {"slot_id": "s1", "constraints": {"max_words": 3}}
        assert length_warnings(slot, "one two three") == []

    def test_char_limit(self):
        slot = {"slot_id": "s1", "constraints": {"max_chars": 5}}
        assert length_warnings(slot, "toolong") and \
            length_warnings(slot, "ok") == []

    def test_no_constraints_no_warnings(self):
        assert length_warnings({"slot_id": "s1"}, "any text at all") == []


class TestVoiceSpecLoader:
    def test_committed_spec_loads_and_carries_all_ten_principles(self):
        text = load_voice_spec(VOICE_DEFAULT)
        for principle in ("Clear", "Concise", "Confident", "Professional",
                          "Client-focused", "Evidence-based", "Consistent",
                          "Solution-oriented", "Transparent",
                          "Action-oriented"):
            assert f"**{principle}**" in text

    def test_wrong_h1_raises(self, tmp_path):
        bad = tmp_path / "v.md"
        bad.write_text("# Voice\n\n## Principles\n1. x\n", encoding="utf-8")
        with pytest.raises(VoiceSpecError):
            load_voice_spec(bad)

    def test_missing_principles_raises(self, tmp_path):
        bad = tmp_path / "v.md"
        bad.write_text("# Firm voice spec\n\nprose only\n", encoding="utf-8")
        with pytest.raises(VoiceSpecError):
            load_voice_spec(bad)

    def test_empty_principles_list_raises(self, tmp_path):
        bad = tmp_path / "v.md"
        bad.write_text("# Firm voice spec\n\n## Principles\n\nnone yet\n",
                       encoding="utf-8")
        with pytest.raises(VoiceSpecError):
            load_voice_spec(bad)

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(VoiceSpecError):
            load_voice_spec(tmp_path / "absent.md")

    def test_extra_sections_tolerated_for_p8_enrichment(self, tmp_path):
        ok = tmp_path / "v.md"
        ok.write_text("# Firm voice spec\n\n## Principles\n1. Clear.\n\n"
                      "## Prohibited words\n- leverage\n", encoding="utf-8")
        assert "Prohibited" in load_voice_spec(ok)


class TestConstraintsEndToEnd:
    """The buyer-instructed lanes over the REAL parser: a gapcase
    workbook variant adds Instructions lines and the whole chain runs
    (the negative pairs — no instruction, no line/warning — live on the
    committed twin in test_draft_content and the units above)."""

    @pytest.fixture(scope="class")
    def instructed(self, tmp_path_factory):
        from tests.drafting.fixtures.drafts import (
            ANSWERED_TEXT,
            make_workbook_variant,
            run_drafting_package,
        )
        tmp = tmp_path_factory.mktemp("draft-instructed")
        variant = make_workbook_variant(tmp, instructions_extra=(
            "State plainly anything not offered in your response.",
            "Limit responses to 10 words.",
        ))
        pursuit, report = run_drafting_package(
            tmp, workbook=variant, dispose=[
                {"section_id": "2-special-requirements",
                 "gap_id": "gap_pur_gapcase_plan_01",
                 "action": "omit_approved", "note": "out of scope"},
                {"section_id": "2-special-requirements",
                 "gap_id": "gap_pur_gapcase_plan_02",
                 "action": "answered", "answer": ANSWERED_TEXT},
            ])
        return pursuit, report

    def test_omission_line_composed_under_the_buyer_instruction(
            self, instructed):
        from tests.drafting.fixtures.drafts import (
            answer_by_ref,
            read_draft,
            section_by_id,
        )
        pursuit, _ = instructed
        special = section_by_id(read_draft(pursuit),
                                "2-special-requirements")
        omitted = answer_by_ref(special, "2.0.1")
        assert omitted["status"] == "omitted"
        assert omitted["omission_stated"] is True
        assert omitted["prose"] == (
            "Not offered: Provide quantum blockchain telemetry "
            "certification evidence for proposed personnel. We state "
            "capability boundaries plainly rather than overstate scope.")

    def test_length_warnings_land_in_the_envelope(self, instructed):
        from tests.drafting.fixtures.drafts import read_draft, section_by_id
        pursuit, _ = instructed
        delivery = section_by_id(read_draft(pursuit), "1-delivery-approach")
        assert delivery["status"] == "drafted"
        assert any("exceeds max_words 10" in w
                   for w in delivery.get("warnings", []))
