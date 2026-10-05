"""P32c (A3's zero-spend half): a replay's self-exclusion reaches the
reviser. A frozen-plan card in `exclude` is withheld at revise time the
way a restricted one is — the open refuses on the trace and the round
completes from what remains."""

from engine.revision import run_round
from engine.runlog import read_run

from tests.revision.fixtures.rounds import (
    ACTOR,
    ROUND_AT,
    add_comment,
    open_round_run,
    validated_pursuit,
)


def test_an_excluded_planned_card_is_withheld_at_revise_time(tmp_path):
    pursuit = validated_pursuit(tmp_path)
    frozen = pursuit.read_frozen("pursuit_plan")
    section = next(s for s in frozen["sections"] if s.get("kb_hits"))
    sid, withheld = section["section_id"], section["kb_hits"][0]["kb_id"]
    add_comment(pursuit, sid, "Tighten the opening paragraph.")
    store, log, caller = open_round_run(tmp_path, pursuit)
    report = run_round(pursuit, caller, log, store, at=ROUND_AT,
                       actor=ACTOR, exclude=frozenset({withheld}))
    log.run_end(status="completed")
    assert report.status == "complete", report.warnings
    run_file = pursuit.root / "runs" / log.run_id / "run.jsonl"
    lines = [r for r in read_run(run_file)
             if r.get("record_type") == "kb_retrieval"
             and r["kb"]["query"] == f"revise:{sid}"]
    assert any(l["kb"]["excluded"] == [withheld]
               and l["kb"]["cards_opened"] == [] for l in lines), lines
    assert not any(withheld in l["kb"]["cards_opened"] for l in lines)
