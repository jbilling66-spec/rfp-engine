"""P26a Group B (P2-29b): a control character in model prose never
reaches drafts/draft.json — the drafting wire refuses it and the section
PENDS with the reason (a named pend beats a failed job); the envelope
validates; the self-check's replacement is held to the same rule."""

import json

from engine.drafting import wire
from tests.drafting.fixtures.drafts import (
    make_drafter_script,
    run_drafting_package,
)


def _script_with_control_char():
    script = make_drafter_script()
    inner = script["section_drafter"]

    def poisoned(prompt: str) -> str:
        text = inner(prompt)
        if prompt.startswith("Task: check."):
            return text
        payload = json.loads(text)
        if "answers" in payload and payload["answers"]:
            payload["answers"][0]["prose"] += " bad\x0bchar"
        elif "prose" in payload:
            payload["prose"] += " bad\x0bchar"
        return json.dumps(payload)

    return {**script, "section_drafter": poisoned}


def test_wire_refuses_control_characters_by_codepoint():
    import pytest
    with pytest.raises(wire.WireError, match="U\\+000B"):
        wire.parse_wire_prose(json.dumps({"prose": "a\x0bb", "kb_ids": []}),
                              opened_ids=set())
    with pytest.raises(wire.WireError, match=r"answers\[0\]"):
        wire.parse_wire_answers(json.dumps({"answers": [
            {"slot_id": "s1", "prose": "x\x0cy", "kb_ids": []}]}),
            requested=["s1"], opened_ids=set())


def test_poisoned_prose_pends_the_section_and_the_envelope_validates(
        tmp_path):
    pursuit, report = run_drafting_package(
        tmp_path, script=_script_with_control_char())
    envelope = pursuit.read_artifact("drafts/draft.json")
    statuses = {s["section_id"]: s["status"] for s in envelope["sections"]}
    assert "pending" in statuses.values()
    pended = [s for s in envelope["sections"] if s["status"] == "pending"]
    assert all("U+000B" in s.get("reason", "") for s in pended)
    raw = (pursuit.root / "drafts" / "draft.json").read_text(encoding="utf-8")
    assert "\x0b" not in raw and "\\u000b" not in raw
    assert report.status in ("complete", "partial")
