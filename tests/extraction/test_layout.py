"""C13: the multicolumn detector over synthetic inputs — two-column and
gutter-less layouts flag; single-column, stacked-blocks, sparse, and
spanning-title pages do not; and the prose-columns test tells a tabled
column layout from a real data table."""

from engine.extraction.layout import looks_like_prose_columns, multicolumn_pages


def _col(x_left, x_right, n=6, y0=100, step=20):
    return [[x_left, y0 + i * step, x_right, y0 + i * step + 12] for i in range(n)]


def test_single_column_does_not_flag():
    assert multicolumn_pages({1: _col(72, 520)}) == []


def test_two_column_page_flags():
    boxes = _col(72, 280) + _col(320, 528)
    assert multicolumn_pages({1: boxes}) == [1]


def test_gutter_less_two_column_flags():
    # The corpus probe's shape: columns abut with no whitespace gutter —
    # x-disjointness, not gutter width, is the criterion.
    boxes = _col(72, 300) + _col(300, 528)
    assert multicolumn_pages({1: boxes}) == [1]


def test_spanning_title_does_not_hide_the_columns():
    title = [[72, 40, 528, 60]]  # full-width heading over both columns
    boxes = title + _col(72, 280) + _col(320, 528)
    assert multicolumn_pages({1: boxes}) == [1]


def test_stacked_blocks_with_different_margins_do_not_flag():
    # x-disjoint but vertically SEQUENTIAL: an indented block below a
    # left block is layout, not columns.
    upper = _col(72, 280, y0=100)
    lower = _col(320, 528, y0=400)
    assert multicolumn_pages({1: upper + lower}) == []


def test_sparse_side_items_do_not_flag():
    # A marginal note next to body text is not a column.
    boxes = _col(72, 400, n=8) + _col(450, 528, n=2)
    assert multicolumn_pages({1: boxes}) == []


def test_bottom_left_origin_convention_also_works():
    # Same two-column page with y decreasing upward (docling PDF origin):
    # only ranges are compared, so the verdict is identical.
    def col(x0, x1):
        return [[x0, 700 - i * 20, x1, 688 - i * 20] for i in range(6)]

    assert multicolumn_pages({1: col(72, 280) + col(320, 528)}) == [1]


def test_multiple_pages_report_sorted():
    two_col = _col(72, 280) + _col(320, 528)
    one_col = _col(72, 520)
    assert multicolumn_pages({3: two_col, 1: two_col, 2: one_col}) == [1, 3]


# -- prose-columns: the layout model's OTHER rendering of a two-column page


def test_tabled_prose_columns_flag():
    # The corpus probe's actual conversion (probed in-container): twelve
    # sentence "cells" in a 6x2 grid.
    grid = [
        [f"RO-{i:02d} Condition clause number {i} applies.",
         f"RO-{i + 6:02d} Condition clause number {i + 6} applies."]
        for i in range(1, 7)
    ]
    assert looks_like_prose_columns(grid) is True


def test_data_table_is_not_prose_columns():
    grid = [["Criterion", "Weight"],
            ["Technical approach", "40%"],
            ["Implementation team", "25%"],
            ["Past performance", "20%"],
            ["Price", "15%"]]
    assert looks_like_prose_columns(grid) is False


def test_requirement_table_with_short_answers_is_not_prose_columns():
    grid = [[f"The vendor shall provide deliverable number {i} on time.", "Yes"]
            for i in range(1, 7)]
    assert looks_like_prose_columns(grid) is False


def test_three_column_table_is_not_prose_columns():
    grid = [["A sentence long enough to read as prose here.", "x", "y"]] * 6
    assert looks_like_prose_columns(grid) is False
