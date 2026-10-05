"""P32c (A3's zero-spend half): `self_exclusion_set` — the purge question
asked of a pursuit instead of a client. A replay of a pursuit must not
retrieve what that pursuit itself put into the firm KB: the cards its
provenance sources name, the cards an accepted proposal sourced from it
landed on or minted, and the transitive derived_from closure over all
of them. The read goes through the restricted store's lineage index —
one authorized, logged read that lets no identifier string out."""

import json

import pytest

from engine.flywheel.proposals import ProposalStore
from engine.kb import KBStore, ProvenanceAccessDenied, self_exclusion_set
from engine.kb.curation import merge_batch

AT = "2026-10-05T09:00:00Z"
FILLS = {"owner": "steward", "verified_date": "2026-10-05"}
BUYER = "Synthetic Harbour Cooperative"


def _prov(pursuit_id, derived=()):
    return {"source_pursuit": pursuit_id, "source_client": BUYER,
            "date": "2026-01-01", "ingested_by": "ingestion_agent",
            "derived_from": list(derived)}


def _card(store, kb_id, pursuit_id, *, derived=(), identifiers=None):
    store.write_card(
        {"kb_id": kb_id, "layer": "corpus", "title": f"Card {kb_id}",
         "summary": f"Summary of {kb_id}.", "use_restriction": False,
         "outcome": "won"},
        f"Body of {kb_id}.", _prov(pursuit_id, derived), identifiers or {})


def _access_lines(store):
    return [json.loads(l) for l in
            store.restricted.access_log.read_text(encoding="utf-8").splitlines()]


def test_the_set_is_the_pursuits_contribution_closed_over_lineage(tmp_path):
    store = KBStore(tmp_path / "kb")
    _card(store, "kb_self0000001", "pur_x")
    _card(store, "kb_deriv000001", "pur_y", derived=["kb_self0000001"])
    _card(store, "kb_deep0000001", "pur_z", derived=["kb_deriv000001"])
    _card(store, "kb_other000001", "pur_y")
    assert self_exclusion_set(store, "pur_x") == frozenset(
        {"kb_self0000001", "kb_deriv000001", "kb_deep0000001"})
    assert self_exclusion_set(store, "pur_y") == frozenset(
        {"kb_deriv000001", "kb_deep0000001", "kb_other000001"})
    assert self_exclusion_set(store, "pur_nobody") == frozenset()


def test_the_set_reaches_through_accepted_proposals(tmp_path):
    """An accepted update_card proposal the pursuit raised landed on a
    card: that card is the pursuit's contribution. An accepted new_card
    proposal minted one: the minted card's provenance names the pursuit
    and its derived_from keeps the lineage. A proposal still `proposed`
    has contributed nothing yet."""
    store = KBStore(tmp_path / "kb")
    _card(store, "kb_base0000001", "pur_other")
    _card(store, "kb_pend0000001", "pur_other")
    proposals = ProposalStore(store.root)
    landed = proposals.open(
        source={"door": "flywheel", "pursuit_id": "pur_x"}, target="corpus",
        kind="update_card", at=AT, kb_id="kb_base0000001",
        diff={"summary": {"before": "Summary of kb_base0000001.",
                          "after": "A sharper summary."}})
    proposals.decide(landed["proposal_id"], decision="accepted",
                     by="steward", at=AT)
    proposals.open(
        source={"door": "flywheel", "pursuit_id": "pur_x"}, target="corpus",
        kind="update_card", at=AT, kb_id="kb_pend0000001",
        diff={"summary": {"after": "Still only proposed."}})
    minted_from = proposals.open(
        source={"door": "ingestion", "pursuit_id": "pur_x"},
        target="fact_sheet", kind="new_card", at=AT, diff={
            "title": {"after": "Twelve depot consolidations delivered"},
            "body": {"after": "We delivered twelve depot consolidations "
                              "for [CLIENT] without a missed cutover."},
            "layer": {"after": "fact_sheet"},
            "grain": {"after": "atom"},
            "content_origin": {"after": "source_text"},
            "derived_from": {"after": ["kb_base0000001"]}})
    before = {c["kb_id"] for c in store.list_cards()}
    merge_batch(store, [minted_from["proposal_id"]], operator="steward",
                at=AT, fills={minted_from["proposal_id"]: FILLS})
    minted = {c["kb_id"] for c in store.list_cards()} - before
    assert len(minted) == 1
    assert self_exclusion_set(store, "pur_x") == frozenset(
        {"kb_base0000001", *minted})
    # the other pursuit's set reaches the minted card through derived_from
    assert self_exclusion_set(store, "pur_other") == frozenset(
        {"kb_base0000001", "kb_pend0000001", *minted})


def test_lineage_index_is_one_logged_read_that_leaks_no_identifier(tmp_path):
    store = KBStore(tmp_path / "kb")
    _card(store, "kb_self0000001", "pur_x",
          identifiers={BUYER: "CLIENT", "$1,975,000": "FEE"})
    _card(store, "kb_deriv000001", "pur_y", derived=["kb_self0000001"])
    index = store.restricted.lineage_index(actor="engine")
    assert index == {
        "kb_self0000001": {"source_pursuits": ["pur_x"], "derived_from": []},
        "kb_deriv000001": {"source_pursuits": ["pur_y"],
                           "derived_from": ["kb_self0000001"]}}
    dumped = json.dumps(index)
    assert BUYER not in dumped and "1,975,000" not in dumped
    line = _access_lines(store)[-1]
    assert (line["actor"], line["purpose"], line["action"], line["granted"]) \
        == ("engine", "replay", "lineage_index", True)
    with pytest.raises(ProvenanceAccessDenied):
        store.restricted.lineage_index(actor="stranger")
    denied = _access_lines(store)[-1]
    assert denied["granted"] is False and denied["action"] == "lineage_index"
