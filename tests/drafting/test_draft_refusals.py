"""The five refusal gates: error record with the named code, refused
report, and ZERO spend (no agent_call line ever lands).

Workspace fixtures are presence-shaped (write_json, not the artifact
seam): every gate here checks existence/status before any content is
parsed, so a minimal dict is the honest minimal fixture. The one
non-refusal in the stack: a malformed/missing voice spec is firm CONFIG
and raises loud (VoiceSpecError), it does not surface as a run error.
"""

import pytest

from engine.drafting import VoiceSpecError
from engine.runlog import read_run
from engine.workspace import PursuitDir
from tests.drafting.fixtures.drafts import run_drafting_run
from tests.helpers import plant_freeze

APPROVED_PLAN = {"status": "approved", "path": "B_free_flow"}


def _bare(tmp_path, *, plan=None, frozen_plan=None, frozen_brief=None):
    pursuit = PursuitDir(tmp_path, "pur_bare")
    if plan is not None:
        pursuit.write_json("plan.json", plan)
    if frozen_plan is not None:
        plant_freeze(pursuit, "pursuit_plan", frozen_plan)
    if frozen_brief is not None:
        plant_freeze(pursuit, "bid_brief", frozen_brief)
    return pursuit


def _assert_refused(pursuit, report, code):
    assert report.status == "refused"
    records = read_run(pursuit.root / "runs" / pursuit.latest_run_id()
                       / "run.jsonl")
    errors = [r for r in records if r["record_type"] == "error"]
    assert [e["error"]["code"] for e in errors] == [code]
    assert not any(r["record_type"] == "agent_call" for r in records)
    assert not any(r["record_type"] == "kb_retrieval" for r in records)


def test_refuses_without_a_plan(tmp_path):
    pursuit = _bare(tmp_path)
    pursuit, report = run_drafting_run(tmp_path, pursuit)
    _assert_refused(pursuit, report, "missing_plan")


def test_refuses_unapproved_plan(tmp_path):
    pursuit = _bare(tmp_path, plan={"status": "gate2_pending"})
    pursuit, report = run_drafting_run(tmp_path, pursuit)
    _assert_refused(pursuit, report, "plan_not_approved")


def test_refuses_without_approved_frozen_plan(tmp_path):
    # v1 harvest: drafting without the Gate-2 ticket refuses.
    pursuit = _bare(tmp_path, plan=APPROVED_PLAN)
    pursuit, report = run_drafting_run(tmp_path, pursuit)
    _assert_refused(pursuit, report, "missing_frozen_plan")


def test_refuses_without_frozen_brief(tmp_path):
    pursuit = _bare(tmp_path, plan=APPROVED_PLAN,
                    frozen_plan=APPROVED_PLAN)
    pursuit, report = run_drafting_run(tmp_path, pursuit)
    _assert_refused(pursuit, report, "missing_frozen_brief")


def test_refuses_path_a_without_slots(tmp_path):
    plan = {"status": "approved", "path": "A_designated",
            "slots_ref": "slots.json"}
    pursuit = _bare(tmp_path, plan=plan, frozen_plan=plan, frozen_brief={})
    pursuit, report = run_drafting_run(tmp_path, pursuit)
    _assert_refused(pursuit, report, "missing_slots")


def test_malformed_voice_spec_raises_not_refuses(tmp_path):
    pursuit = _bare(tmp_path, plan=APPROVED_PLAN, frozen_plan=APPROVED_PLAN,
                    frozen_brief={})
    bad = tmp_path / "bad-voice.md"
    bad.write_text("# Wrong header\n", encoding="utf-8")
    with pytest.raises(VoiceSpecError):
        run_drafting_run(tmp_path, pursuit, voice_path=bad)


def test_refuses_tampered_frozen_plan(tmp_path):
    """P0-2: a frozen plan modified after the gate — a raw write past the
    door, so the gate_2 checkpoint's frozen_sha256 no longer matches — is
    refused before any spend, with the run footer written."""
    import json

    pursuit = _bare(tmp_path, plan=APPROVED_PLAN, frozen_plan=APPROVED_PLAN,
                    frozen_brief={"status": "approved"})
    frozen = pursuit.root / "plan.frozen.json"
    frozen.write_text(json.dumps({**APPROVED_PLAN, "sections": []}),
                      encoding="utf-8")
    pursuit, report = run_drafting_run(tmp_path, pursuit)
    _assert_refused(pursuit, report, "frozen_verification_failed")
