"""C7 (P13): the v2 ingestion wire — the model annotates code-produced
chunks and can no longer segment or edit text. Whitelist discipline is
v1's; the new failure modes (phantom chunk, double annotation) are loud."""

import json

import pytest

from engine.kb.canonical import Element
from engine.kb.chunk import chunk_elements
from engine.kb.ingest import (SECTION_TYPES, TYPE_TAGS,
                              build_annotation_prompt, parse_wire_v2)


def _wire(**overrides) -> str:
    payload = {
        "chunk_annotations": [
            {"chunk": 0, "summary": "Opening exemplar.",
             "section_types": ["exec_summary"],
             "type_tags": ["differentiator"],
             "claim_candidates": ["We completed 40 go-lives."]},
            {"chunk": 1, "summary": "Migration body.",
             "section_types": ["data_migration"],
             "type_tags": ["data_migration"]},
        ],
        "qa_pairs": [{"question": "How long?", "answer": "Four weeks."}],
        "identifiers": [{"value": "Northwind", "type": "CLIENT"},
                        {"value": "$520,000", "type": "FEE"}],
        "client_descriptor": "a K-12 district, ~3,100 employees",
    }
    payload.update(overrides)
    return json.dumps(payload)


def test_wire_parses_to_indexed_annotations():
    wire, cleared = parse_wire_v2(_wire(), "resp_x", n_chunks=2)
    assert set(wire["annotations"]) == {0, 1}
    assert wire["annotations"][0]["claim_candidates"] == \
        ["We completed 40 go-lives."]
    assert wire["annotations"][1]["claim_candidates"] == []
    assert wire["identifiers"] == {"Northwind": "CLIENT",
                                   "$520,000": "FEE"}
    assert cleared == []


def test_out_of_vocab_facets_cleared_and_reported_never_kept():
    wire, cleared = parse_wire_v2(_wire(chunk_annotations=[
        {"chunk": 0, "summary": "s",
         "section_types": ["exec_summary", "invented_type"],
         "type_tags": ["table"]},  # a docling element label, C13's case
    ]), "resp_x", n_chunks=1)
    assert wire["annotations"][0]["section_types"] == ["exec_summary"]
    assert wire["annotations"][0]["type_tags"] == []
    assert {(c["facet"], c["value"]) for c in cleared} == {
        ("section_types", "invented_type"), ("type_tags", "table")}


def test_phantom_chunk_is_wire_drift_not_data():
    with pytest.raises(ValueError, match="names chunk 7"):
        parse_wire_v2(_wire(chunk_annotations=[
            {"chunk": 7, "summary": "s"}]), "resp_x", n_chunks=2)


def test_double_annotation_refused():
    with pytest.raises(ValueError, match="annotated twice"):
        parse_wire_v2(_wire(chunk_annotations=[
            {"chunk": 0, "summary": "a"},
            {"chunk": 0, "summary": "b"}]), "resp_x", n_chunks=2)


def test_missing_chunk_index_refused():
    with pytest.raises(ValueError, match="integer chunk index"):
        parse_wire_v2(_wire(chunk_annotations=[{"summary": "s"}]),
                      "resp_x", n_chunks=1)


def test_unknown_identifier_type_falls_to_redacted():
    wire, cleared = parse_wire_v2(_wire(identifiers=[
        {"value": "ACME-77", "type": "CONTRACT_NO"}]), "resp_x", n_chunks=2)
    assert wire["identifiers"] == {"ACME-77": "REDACTED"}
    assert {"where": "identifiers", "facet": "type",
            "value": "CONTRACT_NO"} in cleared


def test_empty_claim_candidates_dropped():
    wire, _ = parse_wire_v2(_wire(chunk_annotations=[
        {"chunk": 0, "summary": "s",
         "claim_candidates": ["  ", "", "Real claim."]}]),
        "resp_x", n_chunks=1)
    assert wire["annotations"][0]["claim_candidates"] == ["Real claim."]


def test_qa_pair_missing_half_refused():
    with pytest.raises(ValueError, match="lacks question/answer"):
        parse_wire_v2(_wire(qa_pairs=[{"question": "only"}]),
                      "resp_x", n_chunks=2)


def test_annotation_prompt_shape():
    elements = [
        Element(kind="heading", text="1. Approach", level=1),
        Element(kind="paragraph", text="Body of the approach."),
        Element(kind="heading", text="2. Team", level=1),
        Element(kind="table_row", text="Role | Count"),
    ]
    chunks = chunk_elements(elements)
    prompt = build_annotation_prompt("resp_x", chunks, elements)
    assert prompt.startswith("# DOC:resp_x\n")
    assert "<<CHUNK 0: 1. Approach>>" in prompt
    assert "<<CHUNK 1: 2. Team>>" in prompt
    assert "Body of the approach." in prompt
    assert "Role | Count" in prompt
    for vocab in (SECTION_TYPES, TYPE_TAGS):
        assert all(v in prompt for v in vocab)


def test_annotation_prompt_preamble_path_is_named():
    elements = [Element(kind="paragraph", text="Cover letter.")]
    prompt = build_annotation_prompt(
        "resp_x", chunk_elements(elements), elements)
    assert "<<CHUNK 0: (document preamble)>>" in prompt
