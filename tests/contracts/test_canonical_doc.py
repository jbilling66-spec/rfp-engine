"""C2 (P13): the canonical-doc contract — a well-formed L1+L2 model
validates, and the shape refuses drift (unknown keys, malformed spans)."""

import pytest

from engine.contracts import ContractError, validate


def _model() -> dict:
    return {
        "doc_id": "cd_0a1b2c3d4e5f",
        "source_hash": "c" * 64,
        "extractor": "python-docx",
        "extraction_fingerprint": "ext_0123456789abcdef",
        "extraction_status": "clean",
        "media": {"images": 1},
        "elements": [
            {"kind": "heading", "text": "6.0 Accelerators", "level": 1},
            {"kind": "paragraph", "text": "The migration factory ran."},
            {"kind": "table_row", "text": "Criterion | Weight"},
            {"kind": "figure", "text": "", "figure_class": "chart"},
            {"kind": "qa", "text": "Q: How?\n\nA: Carefully."},
        ],
        "chunks": [
            {"doc_path": ["6.0 Accelerators"], "elements": [1, 4],
             "kb_id": "kb_0123456789", "chars": 42, "pages": []},
            {"doc_path": [], "elements": [4, 5], "chars": 24},
        ],
    }


def test_canonical_doc_validates():
    validate("canonical_doc", _model())


def test_unknown_key_refused():
    model = _model()
    model["parsed_at"] = "2026-08-23T00:00:00Z"  # no clocks, no drift
    with pytest.raises(ContractError):
        validate("canonical_doc", model)


def test_unknown_element_kind_refused():
    model = _model()
    model["elements"][0]["kind"] = "footnote"
    with pytest.raises(ContractError):
        validate("canonical_doc", model)


def test_span_must_be_a_pair():
    model = _model()
    model["chunks"][0]["elements"] = [1]
    with pytest.raises(ContractError):
        validate("canonical_doc", model)


def test_doc_id_is_content_addressed_shape():
    model = _model()
    model["doc_id"] = "doc-1"
    with pytest.raises(ContractError):
        validate("canonical_doc", model)
