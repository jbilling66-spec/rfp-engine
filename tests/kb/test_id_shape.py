"""P2-23 (P26b-1, B112): the two stores refuse an id that is not the
shape they accept — prefixed and path-safe, the hex minted form being
the subset fixtures do not use — BEFORE it names a path — every read and write door
crosses `_card_path` / `_path`, so one check covers them all."""

import pytest

from engine.flywheel.proposals import (
    IdShapeError as ProposalIdShapeError, ProposalStore, proposal_id,
    require_proposal_id,
)
from engine.kb.identity import IdShapeError, kb_id_for, require_kb_id
from engine.kb.store import KBStore

BAD = ["../x", "kb_ALPHA0001", "kb_", "kb_alpha0001/../y", "kb_a.b", "", 7, None,
       "kb_alpha0001\n", "kb_alpha 0001", "prop_0123456789ab", "kb_" + "a" * 42]


def test_minted_ids_pass():
    from engine.kb.lanes import ORG_PREFIX, PURSUIT_PREFIX
    assert require_kb_id(PURSUIT_PREFIX + "priorprop01") and require_kb_id(ORG_PREFIX + "note0001")
    assert require_kb_id(kb_id_for("some text")) == kb_id_for("some text")
    pid = proposal_id(source={"s": 1}, kind="edit", kb_id="kb_alpha0001", diff={})
    assert require_proposal_id(pid) == pid


@pytest.mark.parametrize("bad", BAD, ids=[repr(b) for b in BAD])
def test_bad_kb_ids_are_refused_typed(bad):
    with pytest.raises(IdShapeError):
        require_kb_id(bad)


def test_bad_proposal_ids_are_refused_typed():
    for bad in ("../x", "kb_alpha0001", "prop_XYZ", "prop_", "", 7, "prop_a.b"):
        with pytest.raises(ProposalIdShapeError):
            require_proposal_id(bad)


def test_the_card_store_refuses_at_every_door(tmp_path):
    store = KBStore(tmp_path / "kb")
    for door in (store.card_exists, store.read_card, store.delete_card):
        with pytest.raises(IdShapeError):
            door("../escape")
    assert not (tmp_path / "escape.md").exists()


def test_the_proposal_store_refuses_before_writing(tmp_path):
    store = ProposalStore(tmp_path / "kb")
    with pytest.raises(ProposalIdShapeError):
        store.decide("../escape", decision="rejected", by="x",
                     at="2026-01-01T00:00:00", note="")
    with pytest.raises(ProposalIdShapeError):
        store.read("prop_not/hex")
