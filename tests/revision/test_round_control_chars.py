"""P26a Group B (P2-29b), the revision lane: an agent revision carrying a
control character pends its section with the prose UNCHANGED — the round
never half-applies — and a human edit or comment with one is refused at
the events door before anything is pended."""

import json

import pytest

from engine.llm import FakeCaller
from engine.web.events import EventsError, EventsLane
from engine.web.fake_script import derive_revision_wire
from tests.revision.fixtures.rounds import (
    ACTOR,
    ROLE,
    ROUND_AT,
    add_comment,
    round_script,
    run_one_round,
    validated_pursuit,
)


def _poisoned_script():
    script = round_script()

    def poisoned(prompt: str) -> str:
        payload = json.loads(derive_revision_wire(prompt))
        if payload.get("answers"):
            payload["answers"][0]["prose"] += " bad\x0bchar"
        else:
            payload["prose"] = payload.get("prose", "") + " bad\x0bchar"
        return json.dumps(payload)

    script["revision_agent"] = poisoned
    return script


def test_poisoned_revision_pends_the_section_prose_unchanged(tmp_path):
    pursuit = validated_pursuit(tmp_path)
    envelope = pursuit.read_artifact("drafts/draft.json")
    section = next(e for e in envelope["sections"] if e["status"] == "drafted")
    before = json.dumps(section, sort_keys=True)
    add_comment(pursuit, section["section_id"], "Tighten the opening.")
    report, _ = run_one_round(tmp_path, pursuit,
                              fake=FakeCaller(_poisoned_script()))
    assert report.status == "refused"  # nothing changed -> the round refuses
    assert any("U+000B" in w for w in report.warnings)
    after = next(e for e in pursuit.read_artifact("drafts/draft.json")
                 ["sections"] if e["section_id"] == section["section_id"])
    assert json.dumps(after, sort_keys=True) == before
    assert EventsLane(pursuit).pending(), "the comment stays for a later round"


def test_human_edits_and_comments_with_control_characters_refuse_at_the_door(
        tmp_path):
    pursuit = validated_pursuit(tmp_path)
    lane = EventsLane(pursuit)
    section = next(e for e in pursuit.read_artifact("drafts/draft.json")
                   ["sections"] if e["status"] == "drafted")
    sid = section["section_id"]
    with pytest.raises(EventsError, match="text: control character"):
        lane.add_pending(kind="comment", section_id=sid, actor=ACTOR,
                         actor_role=ROLE, at=ROUND_AT, text="hi\x0b")
    with pytest.raises(EventsError, match="after: control character"):
        lane.add_pending(kind="edit", section_id=sid, actor=ACTOR,
                         actor_role=ROLE, at=ROUND_AT, before="a",
                         after="b\x0c")
    assert lane.pending() == []
