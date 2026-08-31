"""C5 (P13): the structure-aware chunker — boundaries follow headings,
nothing follows size. Carries the ROADMAP no-size-limit named test."""

from engine.kb.canonical import Element
from engine.kb.chunk import chunk_elements


def _h(text, level):
    return Element(kind="heading", text=text, level=level)


def _p(text, page=None):
    return Element(kind="paragraph", text=text, page=page)


def test_boundaries_follow_headings():
    elements = [
        _h("1. Approach", 1),
        _p("Intro under approach."),
        _h("1.1 Method", 2),
        _p("Method body."),
        _p("More method body."),
        _h("2. Team", 1),
        _p("Team body."),
    ]
    chunks = chunk_elements(elements)
    assert [(c.doc_path, c.elements) for c in chunks] == [
        (["1. Approach"], (1, 2)),
        (["1. Approach", "1.1 Method"], (3, 5)),
        (["2. Team"], (6, 7)),
    ]


def test_heading_with_only_subheadings_contributes_no_chunk():
    elements = [_h("1. Approach", 1), _h("1.1 Method", 2), _p("Body.")]
    chunks = chunk_elements(elements)
    assert [c.doc_path for c in chunks] == [["1. Approach", "1.1 Method"]]


def test_preamble_before_any_heading_sits_under_empty_path():
    elements = [_p("Cover letter text."), _h("1. Approach", 1), _p("Body.")]
    chunks = chunk_elements(elements)
    assert chunks[0].doc_path == [] and chunks[0].elements == (0, 1)


def test_sibling_heading_pops_the_deeper_level():
    elements = [
        _h("1. Approach", 1), _h("1.1 Method", 2), _p("A."),
        _h("1.2 Tools", 2), _p("B."),
    ]
    chunks = chunk_elements(elements)
    assert [c.doc_path for c in chunks] == [
        ["1. Approach", "1.1 Method"],
        ["1. Approach", "1.2 Tools"],
    ]


def test_figure_and_qa_get_their_own_chunks():
    elements = [
        _h("1. Approach", 1),
        _p("Before the figure."),
        Element(kind="figure", text="", figure_class="chart"),
        _p("After the figure."),
        Element(kind="qa", text="Q: How?\n\nA: Carefully."),
    ]
    chunks = chunk_elements(elements)
    assert [c.elements for c in chunks] == [(1, 2), (2, 3), (3, 4), (4, 5)]
    assert all(c.doc_path == ["1. Approach"] for c in chunks)


def test_no_size_limit_anywhere_giant_section_stays_one_chunk():
    """The ROADMAP clause, by name: a pathologically long section is ONE
    chunk with its size recorded — never split, never truncated (R4/R5).
    A forty-page chunk is an extraction finding to investigate, not
    content to split (KB5: re-chunking orphans edit_survival)."""
    body = [_p(f"Paragraph number {i} of a very long section.")
            for i in range(500)]
    chunks = chunk_elements([_h("3. Migration Approach", 1)] + body)
    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.elements == (1, 501)
    assert chunk.chars == sum(len(e.text) for e in body)


def test_pages_recorded_sorted_unique():
    elements = [
        _h("1. Approach", 1),
        _p("On page two.", page=2), _p("Still page two.", page=2),
        _p("On page three.", page=3),
    ]
    chunks = chunk_elements(elements)
    assert chunks[0].pages == [2, 3]


def test_spans_reconstruct_the_text():
    elements = [_h("1. Approach", 1), _p("A."), _p("B."),
                _h("2. Team", 1), _p("C.")]
    for chunk in chunk_elements(elements):
        start, end = chunk.elements
        assert chunk.chars == sum(
            len(e.text) for e in elements[start:end])
