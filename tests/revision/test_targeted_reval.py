"""The frozen acceptance clause "targeted re-validation only" (B37/D10,
G2): a round re-audits touched sections ONLY, runs consistency exactly
once globally, and never calls the red team — with the absence-rule twin
proving the swept-for calls DO occur under full validation (an absence
test that could never fire proves nothing)."""

import json

from engine.runlog import read_run
from tests.revision.fixtures.rounds import (
    add_comment,
    run_one_round,
    validated_pursuit,
)


def _agent_calls(log_path):
    return [r for r in read_run(log_path)
            if r.get("record_type") == "agent_call"]


def _drafted(pursuit):
    envelope = pursuit.read_artifact("drafts/draft.json")
    return [e for e in envelope["sections"] if e["status"] == "drafted"]


def test_untouched_sections_not_revalidated(tmp_path):
    pursuit = validated_pursuit(tmp_path)
    drafted = _drafted(pursuit)
    assert len(drafted) >= 2, "the twin must offer an untouched section"
    touched = drafted[0]["section_id"]
    add_comment(pursuit, touched, "Sharpen the first answer.")
    _, log = run_one_round(tmp_path, pursuit)
    run_file = sorted((pursuit.root / "runs").glob("*/run.jsonl"))[-1]
    calls = _agent_calls(run_file)
    # claim audit ran for the touched section only
    audit_targets = {c.get("target", {}).get("section_id")
                     for c in calls if c["agent"] == "claim_auditor"}
    assert audit_targets == {touched}
    # consistency exactly once, globally
    assert sum(1 for c in calls
               if c["agent"] == "consistency_checker") == 1
    # the red team is NEVER re-run in a round (stale scores would lie)
    assert not any(c["agent"] == "buyer_red_team" for c in calls)
    # two-section rounds re-audit exactly two
    add_comment(pursuit, drafted[0]["section_id"], "More on scope.")
    add_comment(pursuit, drafted[1]["section_id"], "And here too.")
    _, _ = run_one_round(tmp_path, pursuit)
    run_file = sorted((pursuit.root / "runs").glob("*/run.jsonl"))[-1]
    audit_targets = {c.get("target", {}).get("section_id")
                     for c in _agent_calls(run_file)
                     if c["agent"] == "claim_auditor"}
    assert audit_targets == {drafted[0]["section_id"],
                            drafted[1]["section_id"]}


def test_full_validation_audits_every_section(tmp_path):
    """The absence-rule twin: prove the calls the round SKIPS really do
    occur under full validation — otherwise the counts above could pass
    vacuously against a stack that never calls anything."""
    pursuit = validated_pursuit(tmp_path)
    drafted_ids = {e["section_id"] for e in _drafted(pursuit)}
    validation_run = sorted((pursuit.root / "runs").glob("*/run.jsonl"))[-1]
    calls = _agent_calls(validation_run)
    audit_targets = {c.get("target", {}).get("section_id")
                     for c in calls if c["agent"] == "claim_auditor"}
    assert audit_targets == drafted_ids  # every drafted section audited
    assert any(c["agent"] == "buyer_red_team" for c in calls)


def test_revised_section_drops_red_team_and_keeps_carried(tmp_path):
    pursuit = validated_pursuit(tmp_path)
    before = pursuit.read_artifact("drafts/annotated-draft.json")
    scored = [s["section_id"] for s in before["sections"]
              if "red_team" in s]
    assert scored, "the P8 fixture chain scores drafted sections"
    drafted = _drafted(pursuit)
    touched = next(sid for sid in scored
                   if sid in {e["section_id"] for e in drafted})
    untouched = [sid for sid in scored if sid != touched]
    add_comment(pursuit, touched, "Rework the framing.")
    report, _ = run_one_round(tmp_path, pursuit)
    assert report.status == "complete"
    after = pursuit.read_artifact("drafts/annotated-draft.json")
    by_id = {s["section_id"]: s for s in after["sections"]}
    # the revised section's score is DROPPED — absent means absent
    assert "red_team" not in by_id[touched]
    # carried sections keep theirs
    for sid in untouched:
        assert "red_team" in by_id[sid]
    # ranked_fixes never carry across a round (they describe old prose)
    assert "ranked_fixes" not in after
    # packaging recounted over the union
    assert after["packaging"] == {
        "blocked": any(c.get("disposition") == "block"
                       for s in after["sections"]
                       for c in s.get("claims", [])),
        "tier1_blocks": sum(1 for s in after["sections"]
                            for c in s.get("claims", [])
                            if c.get("disposition") == "block"),
        "waived": sum(1 for s in after["sections"]
                      for c in s.get("claims", [])
                      if c.get("disposition") == "waived"),
    }
