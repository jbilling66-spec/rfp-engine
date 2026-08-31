"""L2 structure-aware chunker (C5, WP13 R4/R5).

Chunk boundaries follow document structure and NOTHING else: a chunk is
the contiguous content under its deepest containing heading, as large as
that section is coherent. There is NO token cap, NO character cap, NO
split-on-size anywhere in this module or downstream — size is recorded
(chars, element count, pages) as a diagnostic on the card's chunk_span
and never enforced. Re-chunking forces re-carding, which orphans every
edit_survival score (KB5): if embeddings arrive, they embed OVER cards;
cards never move.

Figure and qa elements become their own chunks — each mints its own card
(a figure card at C13, a qa_pair card from the wire) and needs its own
backref for descent.

doc_path is the enclosing heading stack, outermost first — NAVIGATION
AND PROVENANCE ONLY (KB10/R9): never a retrieval key, never identity.
"""

from engine.kb.canonical import Chunk, Element


def _span_chunk(elements: list[Element], doc_path: list[str],
                start: int, end: int) -> Chunk:
    span = elements[start:end]
    pages = sorted({e.page for e in span if e.page is not None})
    return Chunk(
        doc_path=list(doc_path),
        elements=(start, end),
        chars=sum(len(e.text) for e in span),
        pages=pages,
    )


def chunk_elements(elements: list[Element]) -> list[Chunk]:
    """Elements in reading order -> chunks with element spans.

    A heading opens a new path level (popping deeper levels); content
    before any heading sits under the empty path; a heading whose only
    content is sub-headings contributes no chunk of its own.
    """
    chunks: list[Chunk] = []
    path: list[tuple[int, str]] = []  # (level, text) stack
    run_start: int | None = None

    def current_path() -> list[str]:
        return [text for _, text in path]

    def flush(end: int) -> None:
        nonlocal run_start
        if run_start is not None and end > run_start:
            chunks.append(
                _span_chunk(elements, current_path(), run_start, end))
        run_start = None

    for index, element in enumerate(elements):
        if element.kind == "heading":
            flush(index)
            level = element.level or 1
            while path and path[-1][0] >= level:
                path.pop()
            path.append((level, element.text))
        elif element.kind in ("figure", "qa"):
            flush(index)
            chunks.append(
                _span_chunk(elements, current_path(), index, index + 1))
        else:
            if run_start is None:
                run_start = index
    flush(len(elements))
    return chunks
