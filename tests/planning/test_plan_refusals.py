"""Planning refusal gates: every code in the table, each with zero
model spend and no plan written. Cheap synthetic workspaces — no chain
needed to prove a refusal."""

from openpyxl import Workbook

from engine.kb import KBStore
from engine.llm import FakeCaller, TracedCaller, effective_config
from engine.planning import run_planning
from engine.runlog import RunLogger, read_run
from engine.version import engine_version
from engine.workspace import PursuitDir
from tests.helpers import plant_freeze


def _workspace(tmp_path, *, brief=None, frozen=None, plan_frozen=False):
    pursuit = PursuitDir(tmp_path, "pur_refusal")
    if brief is not None:
        pursuit.write_artifact("bid_brief", brief)
    if frozen is not None:
        plant_freeze(pursuit, "bid_brief", frozen, validate=True)
    if plan_frozen:
        plant_freeze(pursuit, "pursuit_plan", {
            "pursuit_id": "pur_refusal", "path": "A_designated",
            "sections": [], "status": "approved",
        }, validate=True)
    store = KBStore(tmp_path / "kb")
    log = RunLogger(pursuit.root, pursuit.new_run_id(), pursuit.pursuit_id)
    caller = TracedCaller(FakeCaller({}), log)
    log.run_start(mode="dry_run", engine_version=engine_version(),
                  config=effective_config(), kb_snapshot=store.snapshot())
    return pursuit, store, log, caller


def _brief(status="approved", response_structure="designated"):
    procurement = {}
    if response_structure is not None:
        procurement["response_structure"] = response_structure
    return {"pursuit_id": "pur_refusal", "buyer": {"name": "Synthetic Buyer"},
            "procurement": procurement, "requirements_matrix": [],
            "status": status}


def _assert_refused(pursuit, log, caller, store, code, **kwargs):
    report = run_planning(pursuit, caller, log, store, **kwargs)
    log.run_end(status="completed")
    assert report.status == "refused"
    assert not (pursuit.root / "plan.json").exists()
    records = read_run(log.path)
    assert [r["error"]["code"] for r in records
            if r["record_type"] == "error"] == [code]
    assert not [r for r in records if r["record_type"] == "agent_call"]


def test_missing_brief(tmp_path):
    pursuit, store, log, caller = _workspace(tmp_path)
    _assert_refused(pursuit, log, caller, store, "missing_brief")


def test_brief_not_approved(tmp_path):
    pursuit, store, log, caller = _workspace(tmp_path, brief=_brief("draft"))
    _assert_refused(pursuit, log, caller, store, "brief_not_approved")


def test_missing_frozen_brief(tmp_path):
    pursuit, store, log, caller = _workspace(tmp_path, brief=_brief())
    _assert_refused(pursuit, log, caller, store, "missing_frozen_brief")


def test_plan_frozen(tmp_path):
    pursuit, store, log, caller = _workspace(
        tmp_path, brief=_brief(), frozen=_brief(), plan_frozen=True
    )
    report = run_planning(pursuit, caller, log, store)
    log.run_end(status="completed")
    assert report.status == "refused"
    records = read_run(log.path)
    assert [r["error"]["code"] for r in records
            if r["record_type"] == "error"] == ["plan_frozen"]


def test_missing_response_structure(tmp_path):
    pursuit, store, log, caller = _workspace(
        tmp_path, brief=_brief(),
        frozen=_brief(response_structure=None),
    )
    _assert_refused(pursuit, log, caller, store, "missing_response_structure")


def test_mixed_routes_to_designated_and_wants_targets(tmp_path):
    """P16: mixed is HANDLED (the B37/D28 spec-gap retired) — it rides
    the designated machinery, so with no declared target it refuses for
    the missing documents, not for being mixed."""
    pursuit, store, log, caller = _workspace(
        tmp_path, brief=_brief(), frozen=_brief(response_structure="mixed"),
    )
    _assert_refused(pursuit, log, caller, store, "missing_structure_doc")


def test_hand_edited_frozen_brief_refuses_at_verification(tmp_path):
    """The schema enum blocks an out-of-vocab structure at the writer;
    a hand-edited frozen file planted RAW, past the validating writer,
    used to reach plan.py's own enum check as the second net. Since P25
    item 5 the sha verification is the earlier, stronger net: a freeze
    no gate checkpoint vouches for (or whose bytes changed after the
    gate) never becomes the planning authority at all."""
    import json

    pursuit, store, log, caller = _workspace(tmp_path, brief=_brief())
    corrupt = _brief(response_structure="interpretive_dance")
    (pursuit.root / "brief.frozen.json").write_text(
        json.dumps(corrupt), encoding="utf-8")
    _assert_refused(pursuit, log, caller, store,
                    "frozen_verification_failed")


def test_refuses_frozen_brief_without_gate1_checkpoint(tmp_path):
    """The Gate-1 crash-after-freeze state (freeze on disk, no gate_1
    checkpoint) blocks planning until the gate decision is resubmitted —
    the acceptance's "every frozen-brief read verifies" clause."""
    pursuit, store, log, caller = _workspace(tmp_path, brief=_brief(),
                                             frozen=_brief())
    (pursuit.root / "checkpoints" / "gate_1.json").unlink()
    _assert_refused(pursuit, log, caller, store,
                    "frozen_verification_failed")


def test_declared_target_contradicts_free_flow(tmp_path):
    """P16: a DECLARED target on a free_flow brief refuses — degrading
    to the firm template would silently drop the buyer's own form. A
    legacy-globbed workbook (undeclared) must NOT trigger this."""
    pursuit, store, log, caller = _workspace(
        tmp_path, brief=_brief(),
        frozen=_brief(response_structure="free_flow"),
    )
    stray = tmp_path / "buyer-form.xlsx"
    Workbook().save(stray)
    _assert_refused(pursuit, log, caller, store,
                    "declared_target_contradicts_free_flow",
                    targets=[stray])


def test_unclassifiable_declared_target_refuses_loudly(tmp_path):
    """P16 acceptance: a target the parser cannot classify FAILS LOUDLY,
    never degrading silently to free_flow."""
    pursuit, store, log, caller = _workspace(
        tmp_path, brief=_brief(), frozen=_brief(),
    )
    stray = tmp_path / "form.pdf"
    stray.write_bytes(b"%PDF-1.4 not a form")
    _assert_refused(pursuit, log, caller, store, "unclassifiable_target",
                    targets=[stray])


def test_missing_structure_doc(tmp_path):
    pursuit, store, log, caller = _workspace(
        tmp_path, brief=_brief(), frozen=_brief(),
    )
    _assert_refused(pursuit, log, caller, store, "missing_structure_doc",
                    workbook=None)


def test_empty_parse_refuses_after_parsing(tmp_path):
    wb = Workbook()
    wb.active["A1"] = "Cover letter guidance only."
    slotless = tmp_path / "slotless.xlsx"
    wb.save(slotless)
    pursuit, store, log, caller = _workspace(
        tmp_path / "ws", brief=_brief(), frozen=_brief(),
    )
    _assert_refused(pursuit, log, caller, store, "empty_parse",
                    workbook=slotless)



def test_planning_refuses_an_approved_plan_without_freeze(tmp_path):
    """P0-17: a plan stamped approved with no freeze is the Gate-2 crash
    window. Planning refuses (`plan_past_gate`) instead of rebuilding —
    the human's dispositions live only in plan.json, and it is
    byte-identical after."""
    pursuit, store, log, caller = _workspace(tmp_path, brief=_brief(),
                                             frozen=_brief())
    pursuit.write_artifact("pursuit_plan", {
        "pursuit_id": "pur_refusal", "path": "A_designated", "sections": [],
        "status": "approved",
        "gate2": {"approved_by": "Pat Lead", "at": "2026-08-09T09:00:00"}})
    before = (pursuit.root / "plan.json").read_bytes()
    report = run_planning(pursuit, caller, log, store)
    log.run_end(status="completed")
    assert report.status == "refused"
    assert (pursuit.root / "plan.json").read_bytes() == before
    assert [r["error"]["code"] for r in read_run(log.path)
            if r["record_type"] == "error"] == ["plan_past_gate"]
