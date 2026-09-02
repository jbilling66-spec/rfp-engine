"""The hand-completion record (P26a item 1, P1-27 — the owner's call): values
for the shapes the engine never drafts are validated against the SLOTS
the parser addresses, merged last-write-wins, server-stamped, and read
back as an owed catalogue. Refusals name the slot and the field."""

import hashlib
import json

import pytest

from engine.assembly.hand_fill import (
    HAND_FILL_NAME,
    catalogue,
    completeness,
    hand_slots,
    normalize_values,
    read_hand_fill,
    write_hand_fill,
)
from engine.contracts import ContractError
from engine.planning.plan import REFERENCE_DEFAULT
from engine.structure import merge_parsed, parse_default_template
from engine.workspace import PursuitDir

AT = "2026-09-02T10:00:00Z"
SHA = hashlib.sha256(REFERENCE_DEFAULT.read_bytes()).hexdigest()
META = {"prepared_for_client": "Synthetic Buyer Co", "rfp_title": "Synthetic RFP",
        "rfp_solicitation_number": "RFP-0001", "submitted_by": "The Firm",
        "date_of_submission": "2026-09-30", "primary_contact": "Pat Lead",
        "due_date_method": "2026-10-01, portal"}


@pytest.fixture(scope="module")
def container():
    parsed = parse_default_template(REFERENCE_DEFAULT)
    return {"pursuit_id": "pur_hand", **merge_parsed([parsed])}


def test_the_bundled_template_has_exactly_four_hand_slots(container):
    slots = {s["slot_id"]: s for s in hand_slots(container)}
    assert set(slots) == {"s-front-meta", "s-h10", "s-h11", "s-h12-1"}
    assert slots["s-front-meta"]["response_shape"] == "record"
    assert {f["key"] for f in slots["s-front-meta"]["response_fields"]} \
        == set(META)
    assert [f["key"] for f in slots["s-h11"]["response_fields"]] \
        == ["milestone", "fee", "duration_weeks"]
    assert [f["key"] for f in slots["s-h10"]["response_fields"]] \
        == ["client", "scope", "outcome"]
    assert slots["s-h12-1"]["response_shape"] == "prose"


@pytest.mark.parametrize("values, match", [
    ({"s-h99": "x"}, "not a slot"),
    ({"s-h02": "prose"}, "drafted by the engine"),
    ({"s-front-meta": {"nope": "x"}}, "unknown field"),
    ({"s-front-meta": ["x"]}, "must be an object"),
    ({"s-h11": {"fee": "1"}}, "takes a list"),
    ({"s-h11": [{"fee": "ten"}]}, "must parse as a number"),
    ({"s-h11": [{"duration_weeks": "six"}]}, "must parse as a number"),
    ({"s-h12-1": "bad\x0bchar"}, "control character"),
    ({"s-h10": [{"client": 7}]}, "must be text"),
])
def test_refusals_name_the_slot_and_field(container, values, match):
    with pytest.raises(ContractError, match=match):
        normalize_values(container, values)


def test_normalization_strips_drops_empties_and_accepts_formatted_numbers(
        container):
    out = normalize_values(container, {
        "s-h11": [{"milestone": " Kickoff ", "fee": "$1,200.50",
                   "duration_weeks": "2"}, {"milestone": "", "fee": ""}],
        "s-h12-1": "  Net 30  ",
        "s-front-meta": {"rfp_title": "", "submitted_by": "The Firm"},
        "s-h10": [],
    })
    assert out["s-h11"] == [{"milestone": "Kickoff", "fee": "$1,200.50",
                             "duration_weeks": "2"}]
    assert out["s-h12-1"] == "Net 30"
    assert out["s-front-meta"] == {"submitted_by": "The Firm"}
    assert out["s-h10"] is None  # an empty list clears the slot


def test_write_merges_last_write_wins_clears_and_discards_other_templates(
        tmp_path, container):
    pursuit = PursuitDir(tmp_path, "pur_hand")
    first = write_hand_fill(pursuit, container=container, template_sha256=SHA,
                            entered_by="Pat", at=AT,
                            values={"s-h12-1": "Net 30",
                                    "s-front-meta": {"rfp_title": "One"}})
    assert first["values"] == {"s-h12-1": "Net 30",
                               "s-front-meta": {"rfp_title": "One"}}
    second = write_hand_fill(pursuit, container=container, template_sha256=SHA,
                             entered_by="Sam", at=AT,
                             values={"s-front-meta": META, "s-h12-1": ""})
    assert second["entered_by"] == "Sam"
    assert second["values"] == {"s-front-meta": META}  # inline cleared
    on_disk = json.loads((pursuit.root / HAND_FILL_NAME).read_text())
    assert on_disk == second == read_hand_fill(pursuit)
    # values recorded against ANOTHER template never carry across
    third = write_hand_fill(pursuit, container=container,
                            template_sha256="b" * 64, entered_by="Sam",
                            at=AT, values={"s-h12-1": "Net 45"})
    assert third["values"] == {"s-h12-1": "Net 45"}


def test_completeness_and_the_owed_catalogue(container):
    by_id = {s["slot_id"]: s for s in hand_slots(container)}
    assert completeness(by_id["s-front-meta"], META) == (True, [])
    ok, missing = completeness(by_id["s-front-meta"], {"rfp_title": "x"})
    assert not ok and "submitted_by" in missing
    assert completeness(by_id["s-h11"], None) == (False, ["at least one row"])
    ok, missing = completeness(by_id["s-h11"], [{"milestone": "Kickoff"}])
    assert not ok and missing == ["duration_weeks", "fee"]
    assert completeness(by_id["s-h12-1"], "Net 30") == (True, [])

    rows = {r["slot_id"]: r for r in catalogue(container, {
        "s-front-meta": META, "s-h12-1": "Net 30"})}
    assert rows["s-front-meta"]["status"] == "filled"
    assert rows["s-h12-1"]["status"] == "filled"
    assert rows["s-h11"]["status"] == "owed"
    assert rows["s-h10"]["status"] == "owed"
    assert rows["s-h10"]["docx_anchor"].startswith("10.")
    assert [f["key"] for f in rows["s-h11"]["fields"]] \
        == ["milestone", "fee", "duration_weeks"]
    assert rows["s-h11"]["fields"][1]["type"] == "currency"
