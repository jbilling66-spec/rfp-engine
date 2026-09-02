"""schemas/hand-fill.schema.json — the hand-completion record's contract
(P26a item 1, P1-27). The schema commit's own floor: the three value
shapes validate, and a value that is none of them is refused at the
contract door before any route exists."""

import pytest

from engine.contracts import ContractError, validate

SAMPLE = {
    "pursuit_id": "pur_hand",
    "template_sha256": "a" * 64,
    "entered_by": "Pat Lead",
    "at": "2026-09-02T10:00:00Z",
    "values": {
        "s-front-meta": {"rfp_title": "Synthetic RFP"},
        "s-h11": [{"milestone": "Kickoff", "fee": "1,000"}],
        "s-h12-1": "Net 30 from invoice",
    },
}


def test_record_grid_and_inline_shapes_validate():
    validate("hand_fill", SAMPLE)


@pytest.mark.parametrize("bad", [
    {"s-h11": 5},                       # a number is no value shape
    {"s-h11": [["Kickoff", "1000"]]},   # rows are objects, never lists
    {"s-front-meta": {"rfp_title": 7}},  # every field value is text
])
def test_other_value_shapes_are_refused(bad):
    with pytest.raises(ContractError):
        validate("hand_fill", {**SAMPLE, "values": bad})


def test_the_record_is_closed_and_server_stamped_fields_are_required():
    with pytest.raises(ContractError):
        validate("hand_fill", {**SAMPLE, "extra": 1})
    with pytest.raises(ContractError):
        validate("hand_fill", {k: v for k, v in SAMPLE.items()
                               if k != "entered_by"})
