"""The grounding corpus: three ops docs exist, the vocabulary is closed,
and reading is the only door to citing (P14 acceptance, first clause)."""

import pytest

from engine.assistant.docs import (
    ADVISOR_SOURCES,
    DOC_SOURCES,
    STEWARD_SOURCES,
    corpus_toc,
    read_doc,
)


def test_three_ops_docs_exist_and_corpus_complete():
    """The P14 row's first clause: the three ops docs exist. And the
    whole closed vocabulary resolves — no doc renders (unavailable)."""
    assert STEWARD_SOURCES == ("steward-runbook.md", "maintenance-guide.md",
                               "success-strategies.md")
    for name in DOC_SOURCES:
        body = read_doc(name)
        assert "(unavailable" not in body, f"{name} is missing"
        assert body.strip(), f"{name} is empty"
    toc = corpus_toc()
    assert "(unavailable" not in toc
    assert toc == corpus_toc()  # deterministic


def test_corpus_is_steward_plus_advisor():
    assert set(STEWARD_SOURCES) <= set(DOC_SOURCES)
    assert set(ADVISOR_SOURCES) <= set(DOC_SOURCES)
    assert len(DOC_SOURCES) == len(set(DOC_SOURCES))


def test_unknown_doc_name_refused():
    with pytest.raises(ValueError):
        read_doc("DECISIONS.md")
    with pytest.raises(ValueError):
        read_doc("../CLAUDE.md")
