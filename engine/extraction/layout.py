"""Multicolumn layout detection (C13) — the B57 ACCEPT-WITH-FLAG rendered
as code: reading-order interleave on multicolumn/gutter-less layouts is the
gate's known weak case (report.json: multicolumn_correct false), so the
layouts that can produce it get a mandatory-review flag instead of an
adoption block. The A1 buyer-corpus rerun re-measures whether the weakness
is practical or theoretical — these thresholds are re-tuned there, not
before (B58).

Pure and venv-importable: the worker feeds it per-page text bounding boxes
from docling provenance; tests feed synthetic boxes. The criterion is
x-DISJOINTNESS of side-by-side text blocks, not gutter width — a
gutter-less two-column page (the corpus probe's shape) still splits into
two x-disjoint clusters with overlapping vertical ranges. Boxes spanning
most of the page width (titles, footers) are excluded before clustering so
a heading over two columns cannot hide them.

Two signals, because the layout model itself has two behaviors on such
pages (probed in-container 2026-08-23): it may keep the columns as text
items in interleaved order — the bbox clustering below catches that — or
it may read the gutter-less columns as a TABLE, turning the twelve corpus
probe clauses into a 6x2 grid of interleaved "cells" (this is the
mechanical cause of the gate's recorded multicolumn_correct: false). For
that case, looks_like_prose_columns() marks a two-column table whose cells
read as sentences: prose is not data, and a tabled column layout is
exactly the interleave risk the flag exists for."""

# Tuning constants — recorded, and re-measured at A1 (B58):
MIN_ITEMS_PER_COLUMN = 3  # fewer side-by-side items reads as layout noise
SPANNING_WIDTH_FRACTION = 0.6  # wider than this = full-width furniture
PROSE_CELL_MIN_CHARS = 25  # shorter cells read as data, not sentences
PROSE_CELL_FRACTION = 0.8  # of non-empty cells that must read as prose
PROSE_TABLE_MIN_CELLS = 6


def _y_range(boxes: list) -> tuple[float, float]:
    lo = min(min(b[1], b[3]) for b in boxes)
    hi = max(max(b[1], b[3]) for b in boxes)
    return lo, hi


def _is_multicolumn(boxes: list) -> bool:
    real = [b for b in boxes if b[2] > b[0]]
    if len(real) < 2 * MIN_ITEMS_PER_COLUMN:
        return False
    page_left = min(b[0] for b in real)
    page_right = max(b[2] for b in real)
    width = page_right - page_left
    if width <= 0:
        return False
    body = [b for b in real if (b[2] - b[0]) < SPANNING_WIDTH_FRACTION * width]
    if len(body) < 2 * MIN_ITEMS_PER_COLUMN:
        return False
    body.sort(key=lambda b: (b[0], b[2]))
    for i in range(MIN_ITEMS_PER_COLUMN, len(body) - MIN_ITEMS_PER_COLUMN + 1):
        left, right = body[:i], body[i:]
        boundary = min(b[0] for b in right)
        if max(b[2] for b in left) <= boundary:
            # x-disjoint clusters; multicolumn only if they sit SIDE BY
            # SIDE — their vertical ranges must overlap (stacked blocks
            # with different margins are not columns).
            l_lo, l_hi = _y_range(left)
            r_lo, r_hi = _y_range(right)
            if min(l_hi, r_hi) > max(l_lo, r_lo):
                return True
    return False


def multicolumn_pages(page_boxes: dict) -> list[int]:
    """Pages (1-based, sorted) whose text layout reads as multicolumn.
    `page_boxes`: {page_no: [[left, top, right, bottom], ...]} — either y
    origin convention works; only ranges are compared."""
    return sorted(
        int(page) for page, boxes in page_boxes.items() if _is_multicolumn(boxes)
    )


def looks_like_prose_columns(grid: list) -> bool:
    """A two-column "table" whose cells read as sentences is a tabled
    column layout, not data — the layout model's other rendering of a
    gutter-less page (see module docstring). Data tables fail the prose
    test: their cells are short labels, numbers, or headers."""
    if not grid or any(len(row) != 2 for row in grid):
        return False
    cells = [str(c).strip() for row in grid for c in row if str(c).strip()]
    if len(cells) < PROSE_TABLE_MIN_CELLS:
        return False
    prose = sum(
        1 for c in cells
        if len(c) >= PROSE_CELL_MIN_CHARS and c.endswith(".")
    )
    return prose / len(cells) >= PROSE_CELL_FRACTION
