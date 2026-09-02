"""schemas/feedback-event.schema.json gains `cid` (P26a Group B, P1-14):
a finalized comment/edit event names the pending item it consumed, so a
replayed round commit can dedupe. Optional — every existing event still
validates — and closed: a second unknown key still refuses."""

import pytest

from engine.contracts import ContractError, validate

BASE = {"event_id": "evt_0001", "pursuit_id": "pur_c", "kind": "comment",
        "at": "2026-09-02T10:00:00", "actor_role": "pursuit_lead",
        "comment_text": "tighten"}


def test_cid_validates_and_stays_optional():
    validate("feedback_event", {**BASE, "cid": "cmt_0001"})
    validate("feedback_event", BASE)


def test_the_record_stays_closed():
    with pytest.raises(ContractError):
        validate("feedback_event", {**BASE, "cid": 7})
    with pytest.raises(ContractError):
        validate("feedback_event", {**BASE, "pending_id": "cmt_0001"})
