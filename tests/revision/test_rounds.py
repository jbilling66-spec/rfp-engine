"""The frozen acceptance clause "three comment rounds e2e" + the round
model's honesty guards (B37/D6/D7): revision_n bumps only over changed
bytes, archives keep every prior revision, replies join ONLY their own
round's comments, and a scalar wire (the P8 live bug class) pends the
section without half-applying anything."""

import json

import pytest

from engine.runlog import read_run
from engine.web.events import EventsLane
from tests.revision.fixtures.rounds import (
    ROUND_AT,
    add_comment,
    round_script,
    run_one_round,
    validated_pursuit,
)


def _drafted_section(pursuit):
    envelope = pursuit.read_artifact("drafts/draft.json")
    return next(e for e in envelope["sections"] if e["status"] == "drafted")


def _events(pursuit):
    path = pursuit.root / "events" / "events.jsonl"
    return [json.loads(l) for l in
            path.read_text(encoding="utf-8").splitlines()] \
        if path.exists() else []


def test_three_comment_rounds_e2e(tmp_path):
    pursuit = validated_pursuit(tmp_path)
    section = _drafted_section(pursuit)
    sid = section["section_id"]
    for expected_n in (1, 2, 3):
        entry = add_comment(pursuit, sid,
                            f"Round {expected_n}: tighten the opening.")
        before = _drafted_section(pursuit)["answers"][0]["prose"]
        report, _ = run_one_round(tmp_path, pursuit)
        assert report.status == "complete", report.warnings
        assert report.round_n == expected_n
        assert sid in report.revised
        envelope = pursuit.read_artifact("drafts/draft.json")
        assert envelope["revision_n"] == expected_n  # 1 -> 2 -> 3
        after = _drafted_section(pursuit)["answers"][0]["prose"]
        assert after != before  # prose provably changes per round
        # the archives keep the prior revision pair
        assert (pursuit.root / "revisions"
                / f"draft.rev{expected_n - 1}.json").exists()
        assert (pursuit.root / "revisions"
                / f"annotated.rev{expected_n - 1}.json").exists()
        # the round record joins replies to THIS round's comment only
        record = json.loads((pursuit.root / "revisions"
                             / f"round_{expected_n}.json").read_text())
        assert record["from_revision"] == expected_n - 1
        assert record["reval"]["redteam_dropped"] is True
        events = _events(pursuit)
        finalized = [e for e in events if e["kind"] == "comment"]
        assert len(finalized) == expected_n  # one per consumed round
        assert finalized[-1]["comment_text"] == entry["text"]
        assert finalized[-1]["agent_reply"] == f"Addressed {entry['cid']}."
        # consumed pending is gone
        assert EventsLane(pursuit).pending() == []
    # the annotated draft tracks the envelope at every round
    annotated = pursuit.read_artifact("drafts/annotated-draft.json")
    assert annotated["revision_n"] == 3
    assert annotated["validated_at"] == ROUND_AT


def test_empty_round_refuses_without_bumping(tmp_path):
    pursuit = validated_pursuit(tmp_path)
    report, _ = run_one_round(tmp_path, pursuit)
    assert report.status == "refused"
    assert pursuit.read_artifact("drafts/draft.json")["revision_n"] == 0


def test_failed_round_never_bumps_revision(tmp_path):
    """The planted negative from the acceptance map: a scalar JSON wire
    (the P8 live bug class, F8) pends the section; with nothing else
    changed the round refuses and revision_n stays put."""
    pursuit = validated_pursuit(tmp_path)
    section = _drafted_section(pursuit)
    add_comment(pursuit, section["section_id"], "Please improve this.")
    script = round_script()
    script["revision_agent"] = "null"  # the live model really did this
    before = (pursuit.root / "drafts" / "draft.json").read_bytes()
    report, _ = run_one_round(tmp_path, pursuit, script=script)
    assert report.status == "refused"
    assert section["section_id"] in report.pended
    assert any("pended" in w for w in report.warnings)
    # nothing half-applied: the envelope is byte-identical
    assert (pursuit.root / "drafts" / "draft.json").read_bytes() == before
    # the pended section's comment survives for the next round
    assert len(EventsLane(pursuit).pending()) == 1


def test_human_edit_applies_verbatim_and_anchors(tmp_path):
    pursuit = validated_pursuit(tmp_path)
    section = _drafted_section(pursuit)
    answer = section["answers"][0]
    fragment = answer["prose"].split()[0]
    EventsLane(pursuit).add_pending(
        kind="edit", section_id=section["section_id"],
        slot_id=answer["slot_id"], actor="Robin Reviewer",
        actor_role="pursuit_lead", at=ROUND_AT,
        before=fragment, after="Rewritten-Opening",
        edit_reason="tone")
    report, _ = run_one_round(tmp_path, pursuit)
    assert report.status == "complete"
    revised = _drafted_section(pursuit)["answers"][0]["prose"]
    assert revised.startswith("Rewritten-Opening")
    edit_event = next(e for e in _events(pursuit) if e["kind"] == "edit")
    assert edit_event["before"] == fragment
    assert edit_event["edit_reason"] == "tone"
    # the human's edit was RE-AUDITED (D10): a claim_audit validation
    # line exists for the edited section in the round's run
    runs = sorted((pursuit.root / "runs").glob("*/run.jsonl"))
    records = read_run(runs[-1])
    audits = [r for r in records if r.get("record_type") == "validation"
              and r["validation"]["check"] == "claim_audit"]
    assert any(r["target"]["section_id"] == section["section_id"]
               for r in audits)


def test_unanchored_edit_refuses_the_round(tmp_path):
    pursuit = validated_pursuit(tmp_path)
    section = _drafted_section(pursuit)
    EventsLane(pursuit).add_pending(
        kind="edit", section_id=section["section_id"],
        actor="Robin Reviewer", actor_role="pursuit_lead", at=ROUND_AT,
        before="TEXT THAT IS NOT IN THE PROSE", after="anything")
    report, _ = run_one_round(tmp_path, pursuit)
    assert report.status == "refused"  # nothing changed -> no bump
    assert any("not found verbatim" in w for w in report.warnings)
    assert pursuit.read_artifact("drafts/draft.json")["revision_n"] == 0
