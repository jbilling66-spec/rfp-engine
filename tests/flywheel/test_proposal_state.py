"""P1-39 + M-30 (P26b-2): the proposal store decides ONCE, refuses a
file that is not a proposal record by name, and its id door agrees with
its schema."""

import json
import re

import pytest

from engine.contracts import ContractError
from engine.flywheel.proposals import (PROPOSAL_ID, ProposalStateError,
                                       ProposalStore, require_proposal_id)
from engine.flywheel.proposals import IdShapeError

AT = "2026-09-03T10:00:00Z"
SCHEMA = "schemas/kb-proposal.schema.json"


def _open(store: ProposalStore) -> str:
    return store.open(
        source={"door": "card_edit", "operator": "Sam"}, target="corpus",
        kind="update_card", at=AT, kb_id="kb_alpha0001",
        diff={"summary": {"before": "a", "after": "b"}})["proposal_id"]


def test_a_decision_is_made_once(tmp_path):
    store = ProposalStore(tmp_path / "kb")
    pid = _open(store)
    store.decide(pid, decision="accepted", by="Sam", at=AT)
    with pytest.raises(ProposalStateError, match="already accepted"):
        store.decide(pid, decision="rejected", by="Kim", at=AT)
    decided = store.read(pid)["decided"]
    assert decided == {"by": "Sam", "at": AT, "decision": "accepted"}, \
        "the reject never touched the accepted block"
    with pytest.raises(ProposalStateError):
        store.decide(pid, decision="accepted", by="Sam", at=AT)


def test_a_file_that_is_not_a_proposal_refuses_by_name(tmp_path):
    store = ProposalStore(tmp_path / "kb")
    good = _open(store)
    bad = store.root / "prop_deadbeef0000.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(ContractError, match="prop_deadbeef0000.json"):
        store.list()
    with pytest.raises(ContractError, match="not a JSON record"):
        store.list(status="proposed")
    bad.write_text(json.dumps({"kind": "update_card"}), encoding="utf-8")
    with pytest.raises(ContractError, match="not a proposal record"):
        store.list()
    bad.unlink()
    assert [p["proposal_id"] for p in store.list()] == [good]


def test_an_unknown_proposal_is_not_found_not_a_crash(tmp_path):
    store = ProposalStore(tmp_path / "kb")
    with pytest.raises(FileNotFoundError):
        store.read("prop_0123456789ab")
    with pytest.raises(FileNotFoundError):
        store.decide("prop_0123456789ab", decision="rejected", by="Sam",
                     at=AT)


def test_the_id_door_agrees_with_the_schema():
    from pathlib import Path

    schema = json.loads((Path(__file__).resolve().parents[2] / SCHEMA)
                        .read_text(encoding="utf-8"))
    pattern = schema["properties"]["proposal_id"]["pattern"]
    assert re.compile(pattern.strip("^$")).pattern == PROPOSAL_ID.pattern
    assert require_proposal_id("prop_0123456789ab") == "prop_0123456789ab"
    for bad in ("prop_a", "prop_a-b", "prop_with_underscore", "PROP_ABCD",
                "../escape"):
        with pytest.raises(IdShapeError):
            require_proposal_id(bad)
