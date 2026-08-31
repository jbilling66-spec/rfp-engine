"""C8: the typed extraction view is a strict contract over the gate-proven
dict shape — round-trips exactly, refuses unknown keys, and pins the docling
element-label vocabulary the type_tags exclusion (C13) is defined against."""

import pytest

from engine.extraction.model import (
    DOCLING_ELEMENT_LABELS,
    ExtractionView,
    FigureView,
    TableView,
)

# The C7 worker output shape (gate.py convert_worker), minus gate-only
# timing fields, plus the production-only fields with their defaults.
WORKER_DICT = {
    "grids": [
        {
            "grid": [["Deliverable", "Fee"], ["Data migration", "45,000"]],
            "merges": [[[0, 0], [0, 1]]],
        }
    ],
    "headings": [[1, "Scope of Services"]],
    "figures": [{"classes": [{"label": "logo", "confidence": 0.97}]}],
    "native_comment_texts": ["[author: Reviewer]: confirm the fee cap"],
    "sidecar": {"fills": {"0": {"FFFF00": [[1, 1]]}}, "comment_texts": ["cap"]},
    "text": "# Scope of Services\n\nbody",
    "pages": 3,
    "page_texts": ["p1", "p2", "p3"],
    "multicolumn_pages": [],
    "status": "success",
    "docling_version": "2.121.0",
}


def test_round_trip_is_exact():
    view = ExtractionView.from_dict(WORKER_DICT)
    assert view.to_dict() == WORKER_DICT
    assert isinstance(view.grids[0], TableView)
    assert isinstance(view.figures[0], FigureView)
    assert view.grids[0].merges == [[[0, 0], [0, 1]]]


def test_minimal_dict_takes_defaults():
    view = ExtractionView.from_dict({"text": "body", "pages": 1})
    assert view.status == "success"
    assert view.multicolumn_pages == []
    assert view.sidecar == {"fills": {}, "comment_texts": []}
    assert view.page_texts is None


def test_unknown_key_is_a_refusal_not_a_drop():
    with pytest.raises(ValueError, match="unmodeled keys.*seconds"):
        ExtractionView.from_dict({"text": "b", "pages": 1, "seconds": 2.8})


def test_missing_required_key_refused():
    with pytest.raises(ValueError, match="missing keys.*pages"):
        ExtractionView.from_dict({"text": "b"})


def test_element_label_vocabulary_pinned():
    # Verbatim from the spec's §A5 sentence; C13's disjointness test keys
    # on this constant, so it moves only with the spec.
    assert DOCLING_ELEMENT_LABELS == frozenset(
        {"section_header", "table", "list_item", "figure", "formula"}
    )
