"""P26c (P1-43): steward notes are the ACCEPTED proposals of the note
kinds, read by target — the home a voice-spec, playbook or
validation-tuning proposal lands in when a steward accepts it, and
what the drafter reads. Proposed and rejected ones are not notes; the
text is the human's words; the harness already scans it."""

import pytest

from engine.flywheel.proposals import ProposalStore
from engine.kb.curation import merge_batch
from engine.kb.evalset import retrievable_text
from engine.kb.notes import read_notes, render_notes
from engine.kb.store import KBStore

AT = "2026-09-04T10:00:00Z"


@pytest.fixture
def store(tmp_path):
    return KBStore(tmp_path / "kb")


def _open(store, kind, target, text, *, at=AT, event="evt_0001", **src):
    return ProposalStore(store.root).open(
        source={"door": "flywheel", "pursuit_id": "pur_x",
                "event_ids": [event], **src},
        target=target, kind=kind, at=at,
        diff={"comment": {"after": text}}, note="from section 2")


def test_accepted_note_kinds_project_by_target(store):
    play = _open(store, "playbook_note", "playbook",
                 "Lead with the outcome, not the method.")
    voice = _open(store, "voice_spec_change", "voice_spec",
                  "Drop 'leverage'.", event="evt_0002")
    tune = _open(store, "validation_tuning_note", "validation_tuning",
                 "The SOC 2 date check misfires on a range.",
                 event="evt_0003")
    loose = ProposalStore(store.root).open(
        source={"door": "flywheel", "pursuit_id": "pur_x",
                "event_ids": ["evt_0004"]},
        target="fact_sheet", kind="update_card", at=AT,
        diff={"text": {"before": "seven", "after": "nine"}})
    rejected = _open(store, "playbook_note", "playbook", "Never mind.",
                     event="evt_0005")
    assert read_notes(store.root, ("playbook", "voice_spec")) == [], \
        "proposed is not accepted"
    merge_batch(store, [play["proposal_id"], voice["proposal_id"],
                        tune["proposal_id"], loose["proposal_id"]],
                operator="Sam", at="2026-09-04T11:00:00Z")
    ProposalStore(store.root).decide(rejected["proposal_id"],
                                     decision="rejected", by="Sam", at=AT)
    notes = read_notes(store.root, ("playbook", "voice_spec"))
    assert [n["note_id"] for n in notes] == sorted(
        [play["proposal_id"], voice["proposal_id"]])
    by_target = {n["target"]: n for n in notes}
    assert by_target["playbook"]["text"] == "Lead with the outcome, not the method."
    assert by_target["playbook"]["by"] == "Sam"
    assert by_target["playbook"]["at"] == "2026-09-04T11:00:00Z"
    assert by_target["playbook"]["event_ids"] == ["evt_0001"]
    assert by_target["playbook"]["pursuit_id"] == "pur_x"
    assert by_target["playbook"]["external"] is False
    fact = read_notes(store.root, ("fact_sheet",))
    assert [n["text"] for n in fact] == ["nine"], "an uncited edit is a note"
    assert [n["target"] for n in read_notes(store.root, ("validation_tuning",))] == ["validation_tuning"]
    rendered = render_notes(notes)
    assert "- [playbook] Lead with the outcome" in rendered
    assert "- [voice spec] Drop 'leverage'." in rendered
    assert "Never mind" not in rendered


def test_the_last_n_notes_win_and_the_harness_sees_them(store):
    ids = [_open(store, "playbook_note", "playbook", f"Lesson {i}.",
                 at=f"2026-09-0{i}T10:00:00Z", event=f"evt_00{i:02d}")
           ["proposal_id"] for i in range(1, 6)]
    for i, pid in enumerate(ids, start=1):
        merge_batch(store, [pid], operator="Sam", at=f"2026-09-0{i}T12:00:00Z")
    last_two = read_notes(store.root, ("playbook",), limit=2)
    assert [n["text"] for n in last_two] == ["Lesson 4.", "Lesson 5."]
    assert len(read_notes(store.root, ("playbook",), limit=None)) == 5
    assert "lesson 5." in retrievable_text(store)["proposal"]


def test_a_note_reads_comment_then_reply(store):
    """The record stores diff keys sorted (agent_reply < comment); the
    note reads in the human's order — comment, then the reply."""
    note = ProposalStore(store.root).open(
        source={"door": "flywheel", "pursuit_id": "pur_x",
                "event_ids": ["evt_0001"]},
        target="playbook", kind="playbook_note", at=AT,
        diff={"comment": {"after": "Lead with the outcome."},
              "agent_reply": {"after": "Reordered the opening."}})
    merge_batch(store, [note["proposal_id"]], operator="Sam", at=AT)
    assert read_notes(store.root, ("playbook",))[0]["text"] == (
        "Lead with the outcome. — Reordered the opening.")
