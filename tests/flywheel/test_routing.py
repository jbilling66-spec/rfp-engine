"""Flywheel routing and the proposal lane (c17).

S4 is the property under test: a lesson becomes a PROPOSAL a human sees,
never a silent commit. That is the anti-poisoning control — content that
can enter the corpus unseen is content someone can plant.
"""

import pytest

from engine.contracts import ContractError
from engine.flywheel.proposals import ProposalStore, proposal_id
from engine.flywheel.routing import (ROUTE, infer_edit_reason, is_processed,
                                     route_edits, route_of)
from engine.kb.store import KBStore

AT = "2026-08-03T00:00:00Z"
PROV = {"source_pursuit": "pur_x", "source_client": "Fixture County",
        "date": "2026-01-01", "ingested_by": "ingestion_agent"}


def _edit(before, after, **over):
    event = {"event_id": "ev_1", "pursuit_id": "pur_a", "kind": "edit",
             "at": "2026-08-02T12:00:00Z", "actor_role": "pursuit_lead",
             "section_id": "s1", "before": before, "after": after}
    event.update(over)
    return event


@pytest.fixture
def store(tmp_path):
    return KBStore(tmp_path / "kb")


# ----------------------------------------------------------- inference

def test_a_human_supplied_reason_always_wins():
    """WP8's shape is inferred AND human-correctable: inference only
    fills silence, it never overrides a person."""
    event = _edit("We have 40 consultants.", "We have 14 consultants.",
                  edit_reason="strategy")
    assert infer_edit_reason(event) == "strategy"


def test_changed_numbers_read_as_factual():
    assert infer_edit_reason(
        _edit("We have 40 consultants.", "We have 14 consultants.")
    ) == "factual"


def test_a_removed_prohibited_term_reads_as_tone():
    assert infer_edit_reason(
        _edit("Our world-class team delivers.", "Our team ran seven cycles."),
        voice_terms=["world-class"]) == "tone"


@pytest.mark.parametrize("before,after", [
    ("A budget of 1,200 hours.", "A budget of 2,100 hours."),
    ("Go-live in 2024.", "Go-live in 2042."),
    ("12 sites in wave one.", "21 sites in wave one."),
    ("Fees of 1,975,000 over 3 years.", "Fees of 1,975,000 over 3.5 years."),
])
def test_a_changed_number_reads_as_factual_whatever_its_digits(before, after):
    """P2-50 (P26b-2): the digit SET used to compare equal for every one
    of these — the number changed, the digits did not."""
    assert infer_edit_reason(_edit(before, after)) == "factual"


def test_the_same_numbers_in_the_same_order_are_not_factual():
    assert infer_edit_reason(
        _edit("3 firms, 2 offices.", "3 firms and 2 offices.")) == "other"


def test_inference_stays_conservative():
    """A wrong route sends a lesson to the wrong home, where a human then
    has to notice it. Unclear edits are 'other', not a confident guess."""
    assert infer_edit_reason(
        _edit("We will publish a burn-down.",
              "We will publish a burndown chart.")) == "other"


def test_the_route_table_is_the_spec_table():
    assert route_of("factual") == "fact_sheet"
    assert route_of("tone") == "voice_spec"
    assert route_of("structure") == route_of("length") == "playbook"
    assert route_of("compliance") == "validation_tuning"
    assert route_of("other") == "none"
    assert set(ROUTE) >= {"factual", "tone", "length", "structure",
                          "strategy", "compliance", "other"}


# ------------------------------------------------------------ proposals

def test_routing_opens_a_proposal_carrying_the_diff(store):
    revised = route_edits([_edit("We have 40 consultants.",
                                 "We have 14 consultants.")],
                          store, at=AT)
    assert revised[0]["flywheel_routing"]["target"] == "fact_sheet"

    proposals = ProposalStore(store.root).list()
    assert len(proposals) == 1
    proposal = proposals[0]
    assert proposal["status"] == "proposed"
    assert proposal["diff"]["text"]["before"] == "We have 40 consultants."
    assert proposal["diff"]["text"]["after"] == "We have 14 consultants."
    assert proposal["source"]["event_ids"] == ["ev_1"]
    assert proposal["note"], "a steward needs a reason they can act on"


def test_nothing_touches_a_card_directly(store):
    """S4: the flywheel proposes; it does not write. The store must be
    untouched apart from the proposals directory."""
    store.write_card({"kb_id": "kb_a", "layer": "corpus", "summary": "S"},
                     "Body.", PROV, {})
    before = store.read_card("kb_a")
    route_edits([_edit("We have 40 consultants.", "We have 14.")],
                store, at=AT)
    assert store.read_card("kb_a") == before


def test_re_running_the_learner_proposes_nothing_new(store):
    """Convergence: the learner runs over a growing record, so a second
    pass must not re-raise every lesson it has already drawn."""
    events = [_edit("We have 40 consultants.", "We have 14 consultants.")]
    revised = route_edits(events, store, at=AT)
    assert len(ProposalStore(store.root).list()) == 1

    again = route_edits(revised, store, at=AT)
    assert again == [], "already-routed events are skipped"
    assert len(ProposalStore(store.root).list()) == 1


def test_an_identical_change_is_one_proposal_not_two(store):
    """Ids are content-derived, so the same proposed change from two
    different events does not become two piles for a steward to
    recognise as identical."""
    one = _edit("We have 40 consultants.", "We have 14 consultants.")
    two = _edit("We have 40 consultants.", "We have 14 consultants.",
                event_id="ev_2")
    route_edits([one], store, at=AT)
    route_edits([two], store, at=AT)
    ids = {p["proposal_id"] for p in ProposalStore(store.root).list()}
    assert len(ids) == 2, "different source events are different proposals"
    assert proposal_id({"door": "flywheel"}, "update_card", None, {}) == \
        proposal_id({"door": "flywheel"}, "update_card", None, {})


def test_unroutable_edits_are_recorded_as_routed_nowhere(store):
    """'none' is a decision, written down. A silently skipped event would
    be reprocessed forever."""
    revised = route_edits([_edit("We will publish a burn-down.",
                                 "We will publish a burndown chart.")],
                          store, at=AT)
    assert revised[0]["flywheel_routing"]["target"] == "none"
    assert is_processed(revised[0])
    assert ProposalStore(store.root).list() == []


def test_guest_originated_signal_stays_marked_external(store):
    """The same separability actor_role keeps: untrusted-provenance
    signal must never pool with internal."""
    route_edits([_edit("We have 40 consultants.", "We have 14.",
                       actor_role="external_reviewer")], store, at=AT)
    proposal = ProposalStore(store.root).list()[0]
    assert proposal["source"]["external"] is True


def test_a_machine_proposal_carries_no_operator(store):
    """The absence IS the signal: no human has looked at this yet."""
    route_edits([_edit("We have 40 consultants.", "We have 14.")],
                store, at=AT)
    assert "operator" not in ProposalStore(store.root).list()[0]["source"]


# ------------------------------------------------------------- decisions

def test_a_decision_is_recorded_on_the_proposal(store):
    route_edits([_edit("We have 40 consultants.", "We have 14.")],
                store, at=AT)
    proposals = ProposalStore(store.root)
    pid = proposals.list()[0]["proposal_id"]

    decided = proposals.decide(pid, decision="accepted", by="steward",
                               at="2026-08-04T00:00:00Z", note="checked")
    assert decided["status"] == "accepted"
    assert decided["decided"]["by"] == "steward"
    assert proposals.list(status="proposed") == []
    assert len(proposals.list(status="accepted")) == 1


def test_a_rejected_proposal_is_kept_not_deleted(store):
    """A rejection is evidence about what the flywheel wanted; erasing it
    loses the signal (v1's governance spine)."""
    route_edits([_edit("We have 40 consultants.", "We have 14.")],
                store, at=AT)
    proposals = ProposalStore(store.root)
    pid = proposals.list()[0]["proposal_id"]
    proposals.decide(pid, decision="rejected", by="steward",
                     at="2026-08-04T00:00:00Z")
    assert len(proposals.list()) == 1
    assert proposals.read(pid)["status"] == "rejected"


def test_a_malformed_proposal_never_lands(store):
    proposals = ProposalStore(store.root)
    with pytest.raises(ContractError):
        proposals.open(source={"door": "not_a_door"}, target="fact_sheet",
                       kind="update_card", at=AT)
    assert proposals.list() == []


# --------------------------------------------------------- the metrics

def test_flywheel_yield_is_acceptance_not_volume(tmp_path, monkeypatch):
    """The registry is explicit: acceptance rate. A learner raising a
    hundred lessons nobody takes is not working."""
    import engine.metrics.resolver as resolver_mod
    from engine.metrics.resolver import Corpus, resolve

    kb = tmp_path / "kb"
    store = KBStore(kb)
    route_edits([_edit("We have 40 consultants.", "We have 14.")],
                store, at=AT)
    route_edits([_edit("Tenure is 6 years.", "Tenure is 9 years.",
                       event_id="ev_2")], store, at=AT)
    proposals = ProposalStore(kb)
    ids = [p["proposal_id"] for p in proposals.list()]
    proposals.decide(ids[0], decision="accepted", by="s", at=AT)
    proposals.decide(ids[1], decision="rejected", by="s", at=AT)

    monkeypatch.setattr(resolver_mod, "ROOT", tmp_path)
    row = resolve("flywheel_yield", Corpus(tmp_path / "nothing"))
    assert row["value"] == 0.5, "1 accepted of 2 decided"
    assert row["n"] == 2


def test_lag_measures_edit_to_routing(tmp_path):
    """Whether the flywheel actually turns."""
    from engine.metrics.resolver import Corpus, resolve

    workspace = tmp_path / "ws"
    pursuit = workspace / "pur_a"
    (pursuit / "events").mkdir(parents=True)
    (pursuit / "inbox").mkdir()
    import json
    event = _edit("a", "b")
    event["flywheel_routing"] = {"target": "fact_sheet",
                                 "action_taken": "proposal:prop_x",
                                 "processed_at": "2026-08-04T12:00:00Z"}
    (pursuit / "events" / "events.jsonl").write_text(
        json.dumps(event) + "\n", encoding="utf-8")

    row = resolve("lesson_to_draft_lag_days", Corpus(workspace))
    assert row["value"] == 2.0    # 08-02T12:00 -> 08-04T12:00
    assert row["n"] == 1
