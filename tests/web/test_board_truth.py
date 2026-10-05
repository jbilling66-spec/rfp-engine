"""P26a Group C riders on the board read model: P1-35 — the stage is
decided on the hash BINDINGS the driver decides on (a replanned
pursuit's superseded draft/annotation reads as work to redo, and its
packaging is not published); P2-49 / M-23 — one corrupt file names
itself on its own row instead of 500ing every pursuit; M-25 — the last
run is the numerically latest, not the lexicographically last."""

import json

import pytest

from engine.web import state
from engine.workspace import PursuitDir
from tests.helpers import plant_annotated, plant_freeze


def _pursuit(tmp_path, pid="pur_board"):
    ws = tmp_path / "ws"
    pursuit = PursuitDir(ws, pid)
    (pursuit.root / "brief.json").write_text(json.dumps(
        {"pursuit_id": pid, "status": "approved"}))
    (pursuit.root / "checkpoints").mkdir(exist_ok=True)
    for stage in ("bid_brief", "gate_0"):
        pursuit.checkpoint(stage, {"decision": "approved"})
    plant_freeze(pursuit, "bid_brief", {"pursuit_id": pid})
    (pursuit.root / "plan.json").write_text(json.dumps(
        {"pursuit_id": pid, "status": "approved", "sections": []}))
    plant_freeze(pursuit, "pursuit_plan", {"pursuit_id": pid,
                                           "status": "approved",
                                           "sections": []})
    (pursuit.root / "drafts").mkdir(exist_ok=True)
    (pursuit.root / "drafts" / "draft.json").write_text(json.dumps({
        "pursuit_id": pid, "status": "complete", "revision_n": 0,
        "plan_sha256": pursuit.file_sha256("plan.frozen.json"),
        "sections": []}))
    plant_annotated(pursuit)
    return ws, pursuit


def _row(ws, pid="pur_board"):
    return next(r for r in state.board(ws) if r["pursuit_id"] == pid)


def test_a_current_draft_and_annotation_read_as_review(tmp_path):
    ws, _ = _pursuit(tmp_path)
    row = _row(ws)
    assert row["stage"] == "review" and row["packaging"]["blocked"] is False


def test_a_replan_makes_the_superseded_draft_read_as_drafting_again(tmp_path):
    ws, pursuit = _pursuit(tmp_path)
    plant_freeze(pursuit, "pursuit_plan", {"pursuit_id": "pur_board",
                                           "status": "approved",
                                           "sections": [], "replanned": 1})
    row = _row(ws)
    assert row["stage"] == "drafting"
    assert "packaging" not in row, "a superseded annotation says nothing"


def test_a_stale_annotation_reads_as_validation_again(tmp_path):
    ws, pursuit = _pursuit(tmp_path)
    envelope = json.loads((pursuit.root / "drafts" / "draft.json").read_text())
    envelope["revision_n"] = 1  # the envelope moved; the annotation did not
    (pursuit.root / "drafts" / "draft.json").write_text(json.dumps(envelope))
    row = _row(ws)
    assert row["stage"] == "validation" and "packaging" not in row


def test_one_corrupt_file_names_itself_on_its_own_row_only(tmp_path):
    ws, pursuit = _pursuit(tmp_path)
    other = PursuitDir(ws, "pur_other")
    (other.root / "brief.json").write_text("{not json")
    rows = {r["pursuit_id"]: r for r in state.board(ws)}
    assert rows["pur_board"]["stage"] == "review"
    assert rows["pur_other"]["stage"] == "corrupt"
    assert any("brief.json" in c for c in rows["pur_other"]["corrupt"])
    assert "recovery runbook" in rows["pur_other"]["next"]


def test_last_run_status_picks_the_numerically_latest_run(tmp_path):
    ws, pursuit = _pursuit(tmp_path)
    runs = pursuit.root / "runs"
    for rid, status in (("run_0009", "completed"), ("run_0010", "failed")):
        (runs / rid).mkdir(parents=True)
        (runs / rid / "run.jsonl").write_text(json.dumps({
            "run_id": rid, "pursuit_id": "pur_board", "seq": 0,
            "ts": "2026-09-02T10:00:00Z", "record_type": "run_end",
            "run": {"status": status, "totals": {}}}) + "\n")
    assert _row(ws)["last_run_status"] == "failed"  # run_0010, not run_0009


def test_the_board_row_names_the_buyer_only_when_the_brief_does(tmp_path):
    """P30a (B139): the board row carries the buyer the way the detail
    does — present when the brief names one, absent otherwise."""
    ws, pursuit = _pursuit(tmp_path)
    assert "buyer_name" not in _row(ws)
    brief = json.loads((pursuit.root / "brief.json").read_text())
    brief["buyer"] = {"name": "Example Authority"}
    (pursuit.root / "brief.json").write_text(json.dumps(brief))
    assert _row(ws)["buyer_name"] == "Example Authority"


@pytest.mark.parametrize("name, body", [
    ("events/pending.json", {"pending": [{"cid": "x"}], "next_cid": 1}),
    ("revisions/round_1.json", {"round_n": 1}),
    ("addenda/addm_01/meta.json", {"addendum_id": "addm_01"}),
    ("extraction.json", {"docs": "none"}),
])
def test_a_record_that_fails_its_schema_names_itself_on_its_row(
        tmp_path, name, body):
    """P32b (B145 §3e): the four free-form records have contracts, and
    the board names one that parses but breaks its contract on the
    pursuit's own row — the runbook's stop, never a silent read."""
    ws, pursuit = _pursuit(tmp_path)
    path = pursuit.root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body), encoding="utf-8")
    row = _row(ws)
    assert row["stage"] == "corrupt"
    assert any(c.startswith(f"{name}: fails its schema") for c in row["corrupt"]), \
        row["corrupt"]
    assert "recovery runbook" in row["next"]


def test_a_draft_that_fails_its_schema_names_itself_on_its_row(tmp_path):
    ws, pursuit = _pursuit(tmp_path)
    (pursuit.root / "drafts" / "draft.json").write_text(
        json.dumps({"pursuit_id": "pur_board"}), encoding="utf-8")
    row = _row(ws)
    assert row["stage"] == "corrupt"
    assert any(c.startswith("draft.json: fails its schema") for c in row["corrupt"])
