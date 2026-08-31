"""The advisory questioner (P15/C8, B67 §4): its questions land beside
the completeness gaps marked origin=questioner — uncapped in COUNT,
brevity-capped in FORM (code-enforced, violations dropped-and-reported),
skippable, absent-safe, and consumed by NO gate (E5/A4)."""

import json

import pytest

from engine.contracts import validate
from engine.intake.brief import QUESTION_CHAR_CAP, _brevity_violation
from engine.intake.gate import approve_gate0
from engine.llm import effective_config
from engine.runlog import RunLogger, read_run
from engine.version import engine_version
from tests.intake.fixtures.packages import _wire_from_prompt, run_package

GATE_AT = "2026-08-28T09:00:00Z"


def _with_questions(questions):
    return {"intake_analyst": _wire_from_prompt,
            "intake_questioner": json.dumps({"questions": questions})}


def test_questions_append_beside_completeness_gaps(tmp_path):
    script = _with_questions([
        {"target": "intake.documents",
         "question": "The package references a bid sheet — was it uploaded?"},
        {"question": "Is this a prime bid or a sub to an incumbent prime?"},
    ])
    pursuit, report = run_package(tmp_path, "pdf", script=script)
    brief = pursuit.read_artifact("brief.json")
    validate("bid_brief", brief)
    mine = [g for g in brief["intake"]["gaps"]
            if g["origin"] == "questioner"]
    assert len(mine) == 2
    assert all(g["status"] == "open" and g["reason"] == "needs_sme"
               for g in mine)
    assert mine[0]["target"] == "intake.documents"
    # ids continue the intake numbering — one vocabulary, one sequence
    all_ids = [g["gap_id"] for g in brief["intake"]["gaps"]]
    assert all_ids == sorted(all_ids)
    # and each question reached the run log as an unresolved gap line
    records = read_run(pursuit.root / "runs" / "run_0001" / "run.jsonl")
    logged = {r["gap"]["gap_id"] for r in records
              if r["record_type"] == "gap"}
    assert {g["gap_id"] for g in mine} <= logged
    assert report.status in ("complete", "incomplete")  # never blocked by it


def test_brevity_contract_drops_and_reports(tmp_path):
    """B67 §4 as code: 'clean, crisp questions' — one ask, one sentence,
    one '?', length-capped. Violations are dropped, never rendered."""
    assert _brevity_violation("Short and clear?") is None
    assert _brevity_violation("x" * (QUESTION_CHAR_CAP + 1))  # too long
    assert _brevity_violation("Which form? And which tab?")   # two asks
    assert _brevity_violation("This is a statement.")          # no ask
    assert _brevity_violation("First sentence. Then a question?")

    script = _with_questions([
        {"question": "Good question about the missing attachment?"},
        {"question": "Bad one? And a second ask chained on?"},
        {"question": "No question mark at all."},
    ])
    pursuit, report = run_package(tmp_path, "pdf", script=script)
    brief = pursuit.read_artifact("brief.json")
    mine = [g for g in brief["intake"]["gaps"]
            if g["origin"] == "questioner"]
    assert [g["question_to_human"] for g in mine] == [
        "Good question about the missing attachment?"]
    dropped = [w for w in report.warnings
               if "questioner question dropped" in w]
    assert len(dropped) == 2  # reported, never silent


def test_unscripted_wire_is_unavailable_not_faked(tmp_path):
    """Absent-safe by construction: FakeCaller's default text is not a
    wire, so the run records 'unavailable' and appends nothing — the
    red-team lane's recorded-not-faked rule. This is also what keeps the
    injection twin-pair equality tests and the CI slice green without
    scripting the questioner everywhere."""
    pursuit, report = run_package(tmp_path, "pdf")  # default SCRIPT only
    brief = pursuit.read_artifact("brief.json")
    assert not any(g.get("origin") == "questioner"
                   for g in brief["intake"].get("gaps", []))
    assert any("advisory questions unavailable" in w
               for w in report.warnings)


def test_no_gate_consumes_questioner_output(tmp_path):
    """THE named advisory test (ROADMAP P15 row, E5/A4): every questioner
    question left open, and gate_0 still decides — the question block is
    skippable in the owner's exact sense: it saves time when used, blocks
    nothing when not."""
    script = _with_questions(
        [{"question": f"Open question number {i} left unanswered?"}
         for i in range(1, 6)])  # no cap on count
    pursuit, _ = run_package(tmp_path, "pdf", script=script)
    log = RunLogger(pursuit.root, pursuit.new_run_id(), pursuit.pursuit_id)
    log.run_start(mode="dry_run", engine_version=engine_version(),
                  config=effective_config(), kb_snapshot="kb@empty")
    result = approve_gate0(pursuit, log, decision="approved",
                           actor="Pat Lead", at=GATE_AT)
    log.run_end(status="completed")
    assert result.decision == "approved"
    brief = pursuit.read_artifact("brief.json")
    open_questioner = [g for g in brief["intake"]["gaps"]
                       if g["origin"] == "questioner"
                       and g["status"] == "open"]
    assert len(open_questioner) == 5  # all five survived, all ignored
