"""P32c (A3's zero-spend half): a replay's self-exclusion reaches the
drafter. A planned card in `exclude` is withheld at draft time the way a
restricted one is — the open refuses on the trace, the section says why,
and the section still drafts from what remains."""

from engine.runlog import read_run

from tests.drafting.fixtures.drafts import (
    CANON_ID,
    read_draft,
    run_drafting_package,
    section_by_id,
)

DELIVERY = "1-delivery-approach"


def test_an_excluded_planned_card_is_withheld_at_draft_time(tmp_path):
    pursuit, report = run_drafting_package(
        tmp_path, exclude=frozenset({CANON_ID}))
    assert report.status == "complete"
    section = section_by_id(read_draft(pursuit), DELIVERY)
    assert any(CANON_ID in w and "withheld" in w
               for w in section["warnings"]), section["warnings"]
    runs = sorted((pursuit.root / "runs").glob("*/run.jsonl"))
    lines = [r for r in read_run(runs[-1])
             if r.get("record_type") == "kb_retrieval"
             and r["kb"]["query"] == f"plan:{DELIVERY}"]
    refused = [l for l in lines if l["kb"]["step"] == "targeted_open"
               and l["kb"]["excluded"] == [CANON_ID]]
    assert refused and all(l["kb"]["cards_opened"] == [] for l in refused)
    assert not any(CANON_ID in l["kb"]["cards_opened"] for l in lines)
    assert any(l["kb"]["cards_opened"] for l in lines)  # others still opened
