"""Acceptance clause 2 (frozen, ROADMAP P8): the one RFP_LIVE=1 demo run is
RECORDED — the committed milestone trace proves what it claims. These tests
read `docs/milestones/p8-live-run/runs/` (the verbatim run.jsonl copies from
the 2026-08-08 live slice) and re-derive every property the record asserts:
live mode, gapless sequence, closed footer, totals that reconcile against
the summed call lines, and a validation run that really audited claims and
really wrote the artifact. A record that cannot pass its own replay is not
a record (B34(14) discipline applied to history)."""

import json
from pathlib import Path

from engine.runlog import assert_seq_gapless, read_run

ROOT = Path(__file__).resolve().parents[2]
MILESTONE = ROOT / "docs" / "milestones" / "p8-live-run"


def _runs():
    return sorted((MILESTONE / "runs").glob("*.jsonl"))


def test_milestone_record_is_committed():
    assert MILESTONE.is_dir(), "the P8 live-run milestone record is missing"
    assert len(_runs()) == 6, "one recorded run per slice stage group"


def test_every_recorded_run_is_live_gapless_and_closed():
    for run_file in _runs():
        records = read_run(run_file)
        assert records[0]["run"]["mode"] == "live", run_file.name
        assert_seq_gapless(records)
        footer = records[-1]
        assert footer["record_type"] == "run_end", run_file.name
        assert footer["run"]["status"] == "completed", run_file.name


def test_footer_totals_reconcile_with_the_call_lines():
    for run_file in _runs():
        records = read_run(run_file)
        calls = [r for r in records if r["record_type"] == "agent_call"]
        totals = records[-1]["run"]["totals"]
        assert totals["agent_calls"] == len(calls), run_file.name
        assert totals["cost_usd"] == round(
            sum(c.get("cost_usd", 0.0) for c in calls), 6), run_file.name
        assert totals["input_tokens"] == sum(
            c.get("tokens", {}).get("input", 0) for c in calls), run_file.name
        assert totals["output_tokens"] == sum(
            c.get("tokens", {}).get("output", 0) for c in calls), run_file.name


def test_the_run_actually_spent_money():
    # The whole point of clause 2: this record is live behavior, not a
    # FakeCaller rehearsal wearing a live label.
    total = sum(read_run(f)[-1]["run"]["totals"]["cost_usd"] for f in _runs())
    assert total > 0
    models = {c.get("model") for f in _runs() for c in read_run(f)
              if c["record_type"] == "agent_call"}
    assert not any(m and m.startswith("fake-") for m in models)


def test_validation_run_audited_and_wrote_the_artifact():
    records = read_run(_runs()[-1])
    validations = [r for r in records if r["record_type"] == "validation"]
    assert any(v["validation"].get("check") == "claim_audit"
               for v in validations), \
        "the recorded validation run never audited a claim"
    artifacts = [r for r in records if r["record_type"] == "artifact"]
    assert any("annotated" in json.dumps(a.get("artifact", {}))
               for a in artifacts), \
        "the recorded validation run never wrote the annotated draft"
