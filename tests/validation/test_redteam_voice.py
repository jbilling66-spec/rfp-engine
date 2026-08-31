"""Red-team wire discipline (advisory that never lies, B34(9)) and the
deterministic voice scan over the committed enrichments (B34(10))."""

from pathlib import Path

import pytest

from engine.drafting.compose import VOICE_DEFAULT
from engine.validation import (
    build_redteam_prompt,
    load_anchors,
    parse_redteam_wire,
    prohibited_terms,
    voice_findings,
)

ANCHORS = Path(__file__).resolve().parents[2] / "config" / "references" / "win-theme-anchors.md"

KNOWN = frozenset({"s1", "s2"})


def test_committed_anchors_load_and_frame_the_prompt():
    anchors = load_anchors(ANCHORS)
    assert anchors.count("**Strong**") == 3 and anchors.count("**Weak**") == 3
    prompt = build_redteam_prompt(
        buyer={"name": "Northwind Regional Health", "vertical": "healthcare"},
        criteria=["transition risk (30%)"], anchors=anchors,
        sections=[("s1", "One", "P1")])
    assert prompt.startswith("Task: red-team.")
    assert "transition risk (30%)" in prompt
    assert "rehearsed-cutover record" in prompt  # anchors really framed


def test_malformed_anchors_refused(tmp_path):
    bad = tmp_path / "anchors.md"
    bad.write_text("# Something else\n", encoding="utf-8")
    with pytest.raises(ValueError, match="pinned H1"):
        load_anchors(bad)


def test_redteam_scores_recorded_weak_sections_flagged():
    scores, fixes, findings, warnings = parse_redteam_wire(
        '{"sections": [{"section_id": "s1", "score": 8, "weaknesses": []}, '
        '{"section_id": "s2", "score": 3, "weaknesses": ["generic"]}], '
        '"ranked_fixes": [{"rank": 9, "section_id": "s2", "fix": "be specific"}]}',
        known_ids=KNOWN)
    assert scores["s1"]["score"] == 8 and scores["s2"]["score"] == 3
    assert [f.finding_id for f in findings] == ["red_team:weak_section:s2"]
    assert findings[0].disposition == "advisory"
    assert fixes == [{"rank": 1, "section_id": "s2", "fix": "be specific"}]
    assert warnings == []


def test_redteam_clamps_and_whitelists():
    scores, fixes, findings, warnings = parse_redteam_wire(
        '{"sections": [{"section_id": "s1", "score": 14, "weaknesses": []}, '
        '{"section_id": "ghost", "score": 5, "weaknesses": []}], '
        '"ranked_fixes": [{"rank": 1, "section_id": "ghost", "fix": "x"}]}',
        known_ids=KNOWN)
    assert scores["s1"]["score"] == 10
    assert "ghost" not in scores and fixes == []
    assert any("clamped" in w for w in warnings)
    assert any("unknown section" in w for w in warnings)


def test_redteam_unparseable_is_recorded_not_faked():
    scores, fixes, findings, warnings = parse_redteam_wire(
        "garbage", known_ids=KNOWN)
    assert (scores, fixes, findings) == ({}, [], [])
    assert any("unavailable" in w for w in warnings)


def test_redteam_scalar_json_is_unavailable_not_a_crash():
    # `null` is valid JSON with no subscript (live-model behavior, P8).
    scores, fixes, findings, warnings = parse_redteam_wire(
        "null", known_ids=KNOWN)
    assert (scores, fixes, findings) == ({}, [], [])
    assert any("unavailable" in w for w in warnings)


def test_committed_prohibited_terms_parse_with_variants():
    terms = prohibited_terms(VOICE_DEFAULT)
    assert "leverage" in terms          # qualifier "(verb)" stripped
    assert "world-class" in terms       # split on "/"
    assert "industry-leading" in terms
    assert "we believe" in terms        # multi-word phrase survives
    assert len(terms) >= 20


def test_voice_scan_pair_and_word_boundary():
    terms = ["leverage", "world-class"]
    hits = voice_findings("s1", "We leverage our world-class team.", terms)
    assert sorted(f.finding_id for f in hits) == [
        "voice_polish:prohibited_word:s1:leverage",
        "voice_polish:prohibited_word:s1:world-class"]
    assert all(f.disposition == "advisory" for f in hits)
    # Word-boundary: "leveraged" is not the exact term (inflection coverage
    # is a J3.5/P10 tuning question, deliberately not guessed at here).
    assert voice_findings("s1", "Cleverage systems delivered.", terms) == []


def test_missing_enrichment_section_scans_nothing(tmp_path):
    bare = tmp_path / "voice.md"
    bare.write_text("# Acme voice spec\n\n## Principles\n1. **Clear** — x.\n",
                    encoding="utf-8")
    assert prohibited_terms(bare) == []
