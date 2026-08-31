"""The card store: one writer, round-trip contract, split persistence.

v1 nearly corrupted a pack because two frontmatter writers disagreed on
style; the round-trip and byte-determinism tests here are that lesson as
executable contract.
"""

import pytest

from engine.contracts import ContractError
from engine.kb import KBStore, parse_card, render_card


def _card(kb_id="kb_ab12cd34ef", **overrides):
    card = {
        "kb_id": kb_id,
        "layer": "corpus",
        "doc_kind": "section_exemplar",
        "title": "Implementation methodology — a regional health system",
        "summary": (
            "How [CLIENT] structured a two-wave ERP cutover.\n"
            "Open for the wave plan and the testing gates."
        ),
        "type_tags": ["methodology"],
        "section_types": ["methodology"],
        "outcome": "won",
        "sensitivity": "internal",
        "anonymization": {"status": "anonymized", "placeholders_used": ["[CLIENT]"]},
        "use_restriction": False,
        "legal_hold": False,
        "canonical_block": False,
        "version": 1,
    }
    card.update(overrides)
    return card


PROV = {
    "source_pursuit": "pur_meridian_2025",
    "source_client": "Meridian Health Partners",
    "date": "2025-11-14",
    "ingested_by": "ingestion_agent",
}

IDENTIFIERS = {"Meridian Health Partners": "CLIENT"}

BODY = "A two-wave cutover for [CLIENT], anchored on payroll parallels."


# -- render/parse ----------------------------------------------------------


def test_render_parse_round_trip():
    card, body = _card(), BODY
    assert parse_card(render_card(card, body)) == (card, body)


def test_render_is_byte_deterministic_regardless_of_key_order():
    card = _card()
    shuffled = dict(reversed(list(card.items())))
    assert render_card(card, BODY) == render_card(shuffled, BODY)


def test_render_rejects_provenance_in_frontmatter():
    with pytest.raises(ValueError, match="RESTRICTED"):
        render_card(_card(provenance=PROV), BODY)


def test_parse_requires_both_fences():
    with pytest.raises(ValueError, match="start"):
        parse_card("kb_id: kb_x\n")
    with pytest.raises(ValueError, match="closing"):
        parse_card("---\nkb_id: kb_x\n")


def test_markdown_rule_inside_body_survives_round_trip():
    body = "Before the rule.\n\n---\n\nAfter the rule."
    assert parse_card(render_card(_card(), body)) == (_card(), body)


# -- store -----------------------------------------------------------------


def test_write_card_validates_joined_object_and_writes_nothing_on_failure(tmp_path):
    store = KBStore(tmp_path / "kb")
    bad = _card(layer="bogus_layer")
    with pytest.raises(ContractError):
        store.write_card(bad, BODY, PROV, IDENTIFIERS)
    assert not store.card_exists(bad["kb_id"])
    assert list((tmp_path / "kb" / "restricted" / "provenance").glob("*")) == []


def test_write_then_read_card(tmp_path):
    store = KBStore(tmp_path / "kb")
    store.write_card(_card(), BODY, PROV, IDENTIFIERS)
    card, body = store.read_card("kb_ab12cd34ef")
    assert card == _card()
    assert body == BODY


def test_list_cards_sorted_by_kb_id(tmp_path):
    store = KBStore(tmp_path / "kb")
    for kb_id in ["kb_zz00000000", "kb_aa00000000", "kb_mm00000000"]:
        store.write_card(_card(kb_id=kb_id), BODY, PROV, IDENTIFIERS)
    assert [c["kb_id"] for c in store.list_cards()] == [
        "kb_aa00000000", "kb_mm00000000", "kb_zz00000000",
    ]


def test_delete_card(tmp_path):
    store = KBStore(tmp_path / "kb")
    store.write_card(_card(), BODY, PROV, IDENTIFIERS)
    store.delete_card("kb_ab12cd34ef")
    assert not store.card_exists("kb_ab12cd34ef")
