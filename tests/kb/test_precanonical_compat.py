"""C1 (P13): the kb-card schema after the WP13 merge — pre-canonical
cards still validate (R11), the eight new field groups validate, and
the generated-description conditional refuses at the schema layer
(B59's structural lever, part one of three)."""

import pytest

from engine.contracts import ContractError, validate


def _pre_wp13_card() -> dict:
    """A card shaped exactly as P2–P12 wrote them — none of the WP13
    fields, all of the v2-local governance fields (B12/B8)."""
    return {
        "kb_id": "kb_0123456789",
        "layer": "corpus",
        "doc_kind": "section_exemplar",
        "title": "Data migration approach",
        "summary": "How the migration factory was staffed.",
        "type_tags": ["data_migration"],
        "section_types": ["data_migration"],
        "outcome": "won",
        "sensitivity": "internal",
        "use_restriction": False,
        "legal_hold": False,
        "canonical_block": False,
        "anonymization": {"status": "anonymized",
                          "placeholders_used": ["[CLIENT]"]},
        "version": 1,
    }


def test_pre_wp13_card_still_validates():
    validate("kb_card", _pre_wp13_card())


def test_wp13_fields_validate():
    card = _pre_wp13_card()
    card.update({
        "grain": "chunk",
        "canonical_doc_id": "cd_0123456789ab",
        "doc_path": ["6.0 Accelerators", "6.0.2 Data Migration"],
        "chunk_span": {"chars": 1800, "elements": 4, "pages": [12, 13]},
        "content_origin": "source_text",
        "extraction_status": "clean",
        "identity": {
            "content_hash": "a" * 64,
            "structural_key": "6.0 Accelerators/6.0.2 Data Migration#3",
            "source_hash": "b" * 64,
        },
    })
    validate("kb_card", card)


def test_governance_fields_survived_the_merge():
    """The spec record's copy lacks these five; the hand-merge must not
    have dropped them (the D2 anti-leakage flags and the D1 purge edge
    ride on this)."""
    card = _pre_wp13_card()
    card["provenance"] = {"source_pursuit": "p-001",
                          "source_client": "Northwind",
                          "derived_from": ["kb_aaaaaaaaaa"]}
    card["review_due"] = "2027-01-01"
    validate("kb_card", card)


def test_fact_sheet_still_requires_owner_and_verified_date():
    card = _pre_wp13_card()
    card["layer"] = "fact_sheet"
    with pytest.raises(ContractError):
        validate("kb_card", card)
    card["owner"] = "owner"
    card["verified_date"] = "2026-08-01"
    validate("kb_card", card)


def test_generated_description_can_never_be_a_fact_card():
    """WP13 R13 as structure: the schema itself refuses the combination,
    before fact_catalog's filter belt ever runs."""
    card = _pre_wp13_card()
    card["layer"] = "fact_sheet"
    card["owner"] = "owner"
    card["verified_date"] = "2026-08-01"
    card["content_origin"] = "generated_description"
    with pytest.raises(ContractError):
        validate("kb_card", card)


def test_generated_description_on_corpus_layer_is_legal():
    card = _pre_wp13_card()
    card["content_origin"] = "generated_description"
    card["figure_class"] = "chart"
    validate("kb_card", card)
