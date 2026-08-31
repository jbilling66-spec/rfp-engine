"""Acceptance: the xlsx twin produces a complete brief; hand-extracted
weights match; the hidden twin's concealed directives surface as flags."""

import hashlib

from engine.runlog import assert_seq_gapless, read_run
from tests.intake.fixtures.packages import HAND_WEIGHTS, run_package


def _records(pursuit):
    return read_run(pursuit.root / "runs" / "run_0001" / "run.jsonl")


def test_xlsx_twin_produces_complete_brief(tmp_path):
    pursuit, report = run_package(tmp_path, "xlsx")
    assert report.status == "complete"
    assert report.misses == []
    brief = pursuit.read_artifact("brief.json")
    assert brief["buyer"]["name"] == "Northwind Regional Health"
    assert brief["procurement"]["response_structure"] == "designated"
    assert brief["procurement"]["what_is_bought"]
    assert brief["status"] == "draft"


def test_xlsx_matrix_preserves_duplicate_refs_and_weights_match_hand_extraction(tmp_path):
    pursuit, _ = run_package(tmp_path, "xlsx")
    matrix = pursuit.read_artifact("brief.json")["requirements_matrix"]
    refs = [row.get("ref") for row in matrix]
    assert refs.count("2.0.5") == 2  # EC-2: duplicates preserved, never renumbered
    assert "1.0.1" in refs and "2.0.7" in refs
    weighted = [(row["ref"], row["weight"], row["weight_basis"])
                for row in matrix if "weight" in row]
    assert weighted == HAND_WEIGHTS["xlsx"]  # golden 1: verbatim 30 + percent
    unweighted = [row["ref"] for row in matrix if "weight" not in row]
    assert "2.0.7" in unweighted  # outside the D2:D4 merge


def test_xlsx_partial_weights_warn_not_100(tmp_path):
    _, report = run_package(tmp_path, "xlsx")
    assert any("sum to 90, not 100" in w for w in report.warnings)


def test_xlsx_run_log_shape(tmp_path):
    pursuit, _ = run_package(tmp_path, "xlsx")
    records = _records(pursuit)
    assert_seq_gapless(records)
    stages = [(r["record_type"], r.get("stage")) for r in records
              if r["record_type"] in ("stage_start", "stage_end")]
    assert stages == [("stage_start", "intake"), ("stage_end", "intake"),
                      ("stage_start", "bid_brief"), ("stage_end", "bid_brief")]
    calls = [r for r in records if r["record_type"] == "agent_call"]
    # P15/C8: the advisory questioner is the second call — same stage,
    # mid tier, and every call still traced (no third exists)
    assert [(c["agent"], c["stage"]) for c in calls] == [
        ("intake_analyst", "bid_brief"),
        ("intake_questioner", "bid_brief")]
    screens = [r for r in records if r["record_type"] == "validation"]
    # injection screen, then the C10 extraction record (xlsx is openpyxl's
    # own format: primary, undegraded -> pass).
    assert [s["validation"] for s in screens] == [
        {"check": "injection_screen", "result": "pass"},
        {"check": "extraction", "result": "pass"},
    ]
    artifacts = [r for r in records if r["record_type"] == "artifact"]
    assert len(artifacts) == 1
    assert artifacts[0]["artifact"]["kind"] == "bid_brief"
    actual = hashlib.sha256((pursuit.root / "brief.json").read_bytes()).hexdigest()
    assert artifacts[0]["artifact"]["sha256"] == actual
    run_end = records[-1]
    assert run_end["record_type"] == "run_end"
    assert run_end["run"]["totals"]["agent_calls"] == 2  # analyst + questioner (P15/C8)


def test_hidden_twin_directives_surface_as_flags(tmp_path):
    pursuit, report = run_package(tmp_path, "hidden")
    brief = pursuit.read_artifact("brief.json")
    flags = brief["procurement"]["red_flags"]
    kinds = {f["kind"] for f in flags}
    assert "hidden_content" in kinds  # extracted AND flagged (v1 lesson)
    assert "injection" in kinds  # the directives are instruction-shaped too
    hidden = [f for f in flags if f["kind"] == "hidden_content"]
    locations = {f["source_location"] for f in hidden}
    assert "hidden-twin.xlsx: Internal Notes" in locations
    assert "hidden-twin.xlsx: Vendor Questions" in locations
    records = _records(pursuit)
    screen_records = [r["validation"] for r in records
                      if r["record_type"] == "validation"
                      and r.get("stage") == "intake"]
    assert screen_records == [
        {"check": "injection_screen", "result": "flag"},
        {"check": "extraction", "result": "pass"},
    ]
    # no buyer name exists in this workbook — the brief is honest about it
    assert report.status == "incomplete"
    assert any(r["record_type"] == "gap" for r in records)
