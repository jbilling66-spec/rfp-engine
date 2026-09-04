"""edit_survival (c16) — the last frozen acceptance clause: "heavily-edited
section sinks its cited cards' edit_survival".

The join under test is the one RUN_LOG_DESIGN calls "the whole point":
feedback events meet kb_retrieval cite lines on pursuit_id + section_id,
which is what turns "this section got rewritten" into "these cards
produced content that did not survive".
"""

import pytest

from engine.flywheel.attribution import cards_by_section, edits_by_section, join
from engine.flywheel.survival import (card_survival, section_survival,
                                      text_survival, workspace_survival,
                                      write_card_signals)

PROV = {"source_pursuit": "pur_synthetic", "source_client": "Fixture County",
        "date": "2026-01-01", "ingested_by": "ingestion_agent"}

DRAFTED = ("Our migration factory ran seven mock conversions before the "
           "first production load, with a governed crosswalk workbook "
           "signed off by the controller's office.")
LIGHT_EDIT = ("Our migration factory ran seven mock conversions before the "
              "first production load, with a governed crosswalk workbook "
              "approved by the controller's office.")
HEAVY_EDIT = ("The county will retain its existing chart of accounts; no "
              "conversion work is proposed in this phase.")


def _cite(pursuit_id, section_id, cards, seq=1):
    return {"run_id": "run_0001", "pursuit_id": pursuit_id, "seq": seq,
            "ts": "2026-08-01T09:00:00.000Z", "record_type": "kb_retrieval",
            "stage": "drafting", "agent": "section_drafter",
            "kb": {"query": "q", "step": "cite", "cards_returned": cards,
                   "cards_opened": cards, "cards_cited": cards,
                   "excluded": [], "empty_result": False},
            "target": {"section_id": section_id}}


def _edit(pursuit_id, section_id, before, after, event_id="ev_1"):
    return {"event_id": event_id, "pursuit_id": pursuit_id, "kind": "edit",
            "at": "2026-08-02T12:00:00Z", "actor_role": "pursuit_lead",
            "revision": 1, "edit_reason": "factual",
            "section_id": section_id, "before": before, "after": after}


# ------------------------------------------------- ACCEPTANCE (clause 5)

def test_heavy_edit_sinks_cited_cards():
    """THE clause. One card feeds a heavily rewritten section, another
    feeds a lightly touched one, a third is cited nowhere that was
    edited. Only the first sinks."""
    records = [
        _cite("pur_a", "s_heavy", ["kb_heavy"], seq=1),
        _cite("pur_a", "s_light", ["kb_light"], seq=2),
        _cite("pur_a", "s_clean", ["kb_clean"], seq=3),
    ]
    events = [
        _edit("pur_a", "s_heavy", DRAFTED, HEAVY_EDIT, "ev_h"),
        _edit("pur_a", "s_light", DRAFTED, LIGHT_EDIT, "ev_l"),
    ]
    survival = card_survival(records, events)

    assert survival["kb_heavy"]["survival"] < 0.5, "a rewrite must sink it"
    assert survival["kb_light"]["survival"] > 0.9, "a word change must not"
    assert survival["kb_clean"]["survival"] == 1.0, (
        "a card whose section nobody edited is untouched — not penalised "
        "for silence")
    assert (survival["kb_heavy"]["survival"]
            < survival["kb_light"]["survival"]
            < survival["kb_clean"]["survival"]), "the ranking is the point"


def test_an_uncited_card_gets_no_observation():
    """Non-vacuity in the other direction: a card nobody cited must not
    appear at all, rather than appearing at a default."""
    records = [_cite("pur_a", "s_heavy", ["kb_heavy"])]
    events = [_edit("pur_a", "s_heavy", DRAFTED, HEAVY_EDIT)]
    survival = card_survival(records, events)
    assert set(survival) == {"kb_heavy"}
    assert "kb_never_cited" not in survival


def test_a_cards_score_is_the_mean_over_every_section_it_fed():
    """One bad section must not condemn a card that carried others."""
    records = [_cite("pur_a", "s1", ["kb_shared"], seq=1),
               _cite("pur_a", "s2", ["kb_shared"], seq=2)]
    events = [_edit("pur_a", "s1", DRAFTED, HEAVY_EDIT, "ev_1")]
    survival = card_survival(records, events)
    assert survival["kb_shared"]["observations"] == 2
    heavy_only = card_survival([records[0]], events)["kb_shared"]["survival"]
    assert survival["kb_shared"]["survival"] > heavy_only


# ---------------------------------------------------------- the join

def test_the_join_keys_on_pursuit_and_section():
    """A section id repeated across two pursuits must not pool."""
    records = [_cite("pur_a", "s1", ["kb_a"], seq=1),
               _cite("pur_b", "s1", ["kb_b"], seq=2)]
    keyed = cards_by_section(records)
    assert keyed[("pur_a", "s1")] == {"kb_a"}
    assert keyed[("pur_b", "s1")] == {"kb_b"}


def test_only_cite_steps_attribute():
    """cards_returned is what search found and cards_opened is what the
    drafter read; neither is evidence the content reached the page.
    Attributing an edit to a card merely looked at would sink cards for
    text they never wrote."""
    looked_at = _cite("pur_a", "s1", ["kb_x"])
    looked_at["kb"]["step"] = "card_search"
    assert cards_by_section([looked_at]) == {}


def test_agent_revisions_are_not_human_edits():
    """A comment asks the agent to change something; the agent's own
    revision is the engine's work. Scoring that as an edit would grade
    the engine against itself."""
    comment = {"event_id": "ev_c", "pursuit_id": "pur_a", "kind": "comment",
               "at": "2026-08-02T12:00:00Z", "actor_role": "pursuit_lead",
               "section_id": "s1", "comment_text": "tighten this"}
    assert edits_by_section([comment]) == {}


def test_a_section_with_no_edits_is_an_observation_not_a_gap():
    """Dropping unedited sections would bias the metric toward whatever
    got rewritten — survival would only ever be measured on failures."""
    rows = join([_cite("pur_a", "s1", ["kb_a"])], [])
    assert len(rows) == 1
    assert rows[0]["edits"] == []
    assert section_survival([]) == 1.0


def test_a_section_citing_nothing_yields_no_row():
    empty = _cite("pur_a", "s1", [])
    assert join([empty], []) == []


# --------------------------------------------------------- the math

def test_whitespace_reflow_is_not_an_edit():
    reflowed = DRAFTED.replace(" ", "\n  ")
    assert text_survival(DRAFTED, reflowed) == 1.0


def test_empty_before_scores_one_not_zero():
    """Nothing to survive is not a failure to survive."""
    assert text_survival("", "brand new text") == 1.0


def test_long_section_scores_are_length_independent():
    """P2-45 (P26b-2): with autojunk on, one changed word in a 200+
    character section scored far below the same edit in a short one.
    The same edit scores the same at both lengths, within rounding."""
    short = ("The migration factory ran seven mock conversions before the "
             "first load, each signed off by the controller.")
    long = " ".join(
        f"Wave {n} converted the {kind} ledger with a governed crosswalk "
        f"workbook signed off by the controller's office before load."
        for n, kind in enumerate(("general", "payables", "receivables",
                                  "assets", "payroll", "projects", "grants",
                                  "inventory", "treasury", "budget"), 1))
    assert len(long) > 1200
    short_edit = short.replace("seven", "nine")
    long_edit = long.replace("payroll ledger", "people ledger")
    short_score = text_survival(short, short_edit)
    long_score = text_survival(long, long_edit)
    assert long_score > 0.95
    assert abs(long_score - short_score) < 0.05


def test_survival_is_bounded_and_ordered():
    assert text_survival(DRAFTED, DRAFTED) == 1.0
    assert 0.0 <= text_survival(DRAFTED, "") <= 0.1
    assert (text_survival(DRAFTED, HEAVY_EDIT)
            < text_survival(DRAFTED, LIGHT_EDIT))


# ------------------------------------- writer and resolver cannot diverge

def test_a_routed_copy_does_not_double_count_its_edit():
    """P1-41: the accept door appends a revised copy of a routed edit
    (same event_id). Read through the walker's last-wins collapse it is
    one edit; fed raw it must still not be attributed twice."""
    from engine.metrics.walker import last_wins

    edit = _edit("pur_a", "s_heavy", DRAFTED, HEAVY_EDIT)
    revised = {**edit, "flywheel_routing": {
        "target": "fact_sheet", "action_taken": "proposal:prop_x",
        "processed_at": "2026-08-03T12:00:00Z"}}
    records = [_cite("pur_a", "s_heavy", ["kb_heavy"])]
    once = card_survival(records, [edit])
    twice = card_survival(records, last_wins([edit, revised]))
    assert twice == once
    assert twice["kb_heavy"]["observations"] == 1


def test_the_card_writer_stores_what_the_resolver_reports(tmp_path):
    """B40/D18: one implementation, two consumers. The number persisted
    onto a card is the number the metric reports, because both call the
    same function."""
    from engine.kb.store import KBStore

    store = KBStore(tmp_path / "kb")
    store.write_card(
        {"kb_id": "kb_heavy", "layer": "corpus", "doc_kind": "section_exemplar",
         "title": "Data Migration Approach", "summary": "Migration factory."},
        "Body text.", PROV, {})

    records = [_cite("pur_a", "s_heavy", ["kb_heavy"])]
    events = [_edit("pur_a", "s_heavy", DRAFTED, HEAVY_EDIT)]

    written = write_card_signals(store, records, events)
    assert written == ["kb_heavy"]
    card, body = store.read_card("kb_heavy")
    assert card["edit_survival"] == card_survival(records, events)[
        "kb_heavy"]["survival"]
    assert body.strip() == "Body text.", "the body is never touched"


def test_writing_the_signal_is_convergent(tmp_path):
    """Recomputed from the full record, not accumulated — so running it
    twice lands on the same answer rather than drifting."""
    from engine.kb.store import KBStore

    store = KBStore(tmp_path / "kb")
    store.write_card(
        {"kb_id": "kb_heavy", "layer": "corpus", "doc_kind": "section_exemplar",
         "title": "T", "summary": "S"}, "B", PROV, {})
    records = [_cite("pur_a", "s_heavy", ["kb_heavy"])]
    events = [_edit("pur_a", "s_heavy", DRAFTED, HEAVY_EDIT)]

    write_card_signals(store, records, events)
    once = store.read_card("kb_heavy")[0]["edit_survival"]
    write_card_signals(store, records, events)
    assert store.read_card("kb_heavy")[0]["edit_survival"] == once


def test_a_missing_card_is_skipped_not_an_error(tmp_path):
    """A purged or renamed card must not break the flywheel."""
    from engine.kb.store import KBStore

    store = KBStore(tmp_path / "kb")
    records = [_cite("pur_a", "s1", ["kb_gone"])]
    events = [_edit("pur_a", "s1", DRAFTED, HEAVY_EDIT)]
    assert write_card_signals(store, records, events) == []


def test_the_resolver_reports_it_and_absent_when_unobserved():
    from pathlib import Path

    from engine.metrics.resolver import Corpus, resolve

    corpus = Corpus(Path(__file__).resolve().parents[1] / "fixtures" / "pursuits")
    row = resolve("edit_survival_rate", corpus)
    assert row["status"] in ("value", "count_only")
    assert row["value"] == workspace_survival(corpus)[0]

    empty = Corpus(Path("/nonexistent-workspace"))
    assert resolve("edit_survival_rate", empty)["status"] == "absent"
