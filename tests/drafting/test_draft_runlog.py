"""The drafting run's golden trace shape (hand-derived, gapcase),
spans, targets, the cite line, and totals reconciliation.

Ordering is by seq (O1: parallel drafters will interleave at P9; the
trace is parallel-shaped now). k — the delivery section's kb_hits count
— is read from the P6-golden-tested frozen plan, not hardcoded.
"""

import pytest

from engine.runlog import assert_seq_gapless, read_run
from tests.drafting.fixtures.drafts import (
    CANON_ID,
    make_drafter_script,
    run_drafting_package,
)

DELIVERY = "1-delivery-approach"
SPECIAL = "2-special-requirements"


@pytest.fixture(scope="module")
def traced(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("draft-runlog")
    pursuit, report = run_drafting_package(tmp, script=make_drafter_script())
    assert report.status == "complete"
    records = read_run(pursuit.root / "runs" / "run_0005" / "run.jsonl")
    k = len(next(s for s in pursuit.read_artifact("plan.frozen.json")
                 ["sections"] if s["section_id"] == DELIVERY)["kb_hits"])
    return pursuit, records, k


def test_golden_span_sequence(traced):
    _, records, k = traced
    shape = [(r["record_type"], r.get("stage")) for r in records]
    expected = (
        [("run_start", None),
         ("stage_start", "drafting"),
         ("artifact", "drafting"),      # draft.json skeleton (prepass)
         ("artifact", "drafting")]      # plan.json draft_status planned
        + [("kb_retrieval", "drafting")] * k   # delivery opens
        + [("agent_call", "drafting"),          # delivery draft
           ("agent_call", "drafting"),          # delivery check
           ("kb_retrieval", "drafting"),        # delivery cite
           ("agent_call", "drafting"),          # special draft (no opens)
           ("agent_call", "drafting"),          # special check
           ("kb_retrieval", "drafting"),        # special cite (empty)
           ("artifact", "drafting"),            # draft.json complete
           ("artifact", "drafting"),            # plan.json drafted
           ("stage_end", "drafting"),
           ("run_end", None)]
    )
    assert shape == expected
    assert_seq_gapless(records)


def test_spans_are_parallel_shaped(traced):
    _, records, _ = traced
    stage_start = next(r for r in records if r["record_type"] == "stage_start")
    assert stage_start["span_id"] == "stage:drafting"
    calls = [r for r in records if r["record_type"] == "agent_call"]
    assert [c["span_id"] for c in calls] == [
        f"{DELIVERY}:draft", f"{DELIVERY}:check",
        f"{SPECIAL}:draft", f"{SPECIAL}:check",
    ]
    assert {c["parent_span"] for c in calls} == {"stage:drafting"}


def test_targets_carry_section_id_and_type(traced):
    _, records, _ = traced
    worked = [r for r in records
              if r["record_type"] in ("agent_call", "kb_retrieval")]
    assert worked
    for record in worked:
        assert record["target"]["section_id"] in (DELIVERY, SPECIAL)
    types = {r["target"]["section_id"]: r["target"]["section_type"]
             for r in worked}
    # Delivery's slot text names data migration — the specific family
    # outranks the title's broad "approach" (route table order).
    assert types == {DELIVERY: "data_migration", SPECIAL: "other"}


def test_canonical_card_cited_on_the_cite_line(traced):
    # Acceptance: "canonical block ... with its card cited in kb_retrieval".
    _, records, _ = traced
    cites = [r for r in records if r["record_type"] == "kb_retrieval"
             and r["kb"]["step"] == "cite"]
    assert len(cites) == 2  # uniform: one per drafted section
    delivery = next(r for r in cites
                    if r["target"]["section_id"] == DELIVERY)
    kb = delivery["kb"]
    assert CANON_ID in kb["cards_cited"]
    assert set(kb["cards_cited"]) <= set(kb["cards_opened"])
    assert set(kb["cards_opened"]) <= set(kb["cards_returned"])
    assert kb["query"] == f"plan:{DELIVERY}"
    special = next(r for r in cites
                   if r["target"]["section_id"] == SPECIAL)
    assert special["kb"] == {
        "query": f"plan:{SPECIAL}", "step": "cite", "cards_returned": [],
        "cards_opened": [], "cards_cited": [], "excluded": [],
        "empty_result": True,
    }


def test_planted_bad_cite_never_reaches_the_line(tmp_path):
    pursuit, _ = run_drafting_package(
        tmp_path, script=make_drafter_script(plant_cite_unopened=True))
    records = read_run(pursuit.root / "runs" / "run_0005" / "run.jsonl")
    cites = [r["kb"]["cards_cited"] for r in records
             if r["record_type"] == "kb_retrieval"
             and r["kb"]["step"] == "cite"]
    assert cites  # the lines landed — the emitter did not refuse them
    assert all("kb_unopened99" not in cited for cited in cites)
    envelope = pursuit.read_artifact("drafts/draft.json")
    assert any("kb_unopened99" in w
               for s in envelope["sections"]
               for w in s.get("warnings", []))


def test_totals_reconcile(traced):
    _, records, _ = traced
    footer = records[-1]["run"]
    assert footer["status"] == "completed"
    totals = footer["totals"]
    assert totals["agent_calls"] == 4
    assert totals["cost_usd"] > 0  # synthetic dollars, metered
    assert totals["gaps_opened"] == 0  # drafting opens no gaps (B31(14))
    emitted_cost = round(sum(r["cost_usd"] for r in records
                             if r["record_type"] == "agent_call"), 6)
    assert totals["cost_usd"] == emitted_cost
