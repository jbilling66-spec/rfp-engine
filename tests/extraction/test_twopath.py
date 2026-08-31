"""C8: the shared two-path tripwire — agreement is silent, every divergence
is a finding, and a table the VLM path lacks is a finding, never a skip."""

from engine.extraction.twopath import two_path_review


def _t(grid):
    return {"grid": grid, "merges": []}


def test_agreement_is_empty():
    grids = [_t([["Fee", "45,000"], ["Term", "3 years"]])]
    review = two_path_review(grids, grids)
    assert review == {"tables_diffed": 1, "findings": []}


def test_divergent_cell_is_a_finding_with_table_index():
    det = [_t([["Fee", "45,000"]]), _t([["Term", "3 years"]])]
    vlm = [_t([["Fee", "45,000"]]), _t([["Term", "5 years"]])]
    review = two_path_review(det, vlm)
    assert review["tables_diffed"] == 2
    assert review["findings"] == [
        {"table": 1, "row": 0, "col": 1, "kind": "value_differs",
         "a": "3 years", "b": "5 years"}
    ]


def test_missing_vlm_table_diffs_against_empty():
    det = [_t([["only", "here"]])]
    review = two_path_review(det, [])
    assert review["tables_diffed"] == 1
    assert {f["kind"] for f in review["findings"]} == {"only_in_a"}
    assert len(review["findings"]) == 2


def test_ragged_grids_diff_cell_by_cell():
    det = [_t([["a", "b", "c"]])]
    vlm = [_t([["a", "b"]])]
    review = two_path_review(det, vlm)
    assert review["findings"] == [
        {"table": 0, "row": 0, "col": 2, "kind": "only_in_a", "a": "c"}
    ]


def test_no_tables_no_findings():
    assert two_path_review([], []) == {"tables_diffed": 0, "findings": []}
