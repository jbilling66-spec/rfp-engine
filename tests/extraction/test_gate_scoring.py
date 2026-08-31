"""Gate-scorer can-fail proofs (C5, B51) — offline, before any compute.

The gate must be able to reject docling ("a real possibility, not a
formality"): every scorer here is fed the defect it exists to catch and
must fire, plus the clean twin proving it stays quiet. The kill-criteria
evaluator is driven through all five §A2.4 criteria one at a time.
"""

from __future__ import annotations

import pytest

from engine.extraction.gate import (
    CELL_ACCURACY_BAR,
    P95_BAR_S_PER_PAGE,
    constraint_probe,
    diff_cell_grids,
    evaluate_kill_criteria,
    fabricated_cells,
    p95,
    reading_order_ok,
    score_cell_accuracy,
)

GRID = [["Module", "Year 1"], ["Finance", "420,000"], ["Supply Chain", "310,000"]]


# ------------------------------------------------------------ two-path diff


def test_cell_diff_stays_quiet_on_agreement():
    assert diff_cell_grids(GRID, [row[:] for row in GRID]) == []


def test_cell_diff_flags_planted_fabrication():
    vlm = [row[:] for row in GRID]
    vlm[1][1] = "421,000"  # the invented cell
    findings = diff_cell_grids(GRID, vlm)
    assert findings == [
        {"row": 1, "col": 1, "kind": "value_differs", "a": "420,000", "b": "421,000"}
    ]


def test_cell_diff_flags_cells_present_in_only_one_path():
    shorter = [row[:] for row in GRID][:2]
    findings = diff_cell_grids(GRID, shorter)
    assert {f["kind"] for f in findings} == {"only_in_a"}
    assert len(findings) == 2  # the whole dropped row, cell by cell


# ------------------------------------------------------- fabrication vs key


def test_fabricated_cells_flags_invented_content():
    extracted = [row[:] for row in GRID]
    extracted[2][1] = "999,999"  # appears nowhere in the source
    assert fabricated_cells(extracted, GRID) == [{"row": 2, "col": 1, "text": "999,999"}]


def test_position_shifts_of_real_content_are_not_fabrication():
    shifted = [GRID[0], GRID[2], GRID[1]]  # rows swapped: accuracy error, not invention
    assert fabricated_cells(shifted, GRID) == []


# ---------------------------------------------------------------- accuracy


def test_cell_accuracy_scores_the_truth_denominator():
    """Dropping cells cannot raise the score: every truth cell is scored."""
    partial = [GRID[0], GRID[1]]  # third row dropped
    scored = score_cell_accuracy(partial, GRID)
    assert scored == {"correct": 4, "total": 6, "accuracy": 4 / 6}
    assert score_cell_accuracy(GRID, GRID)["accuracy"] == 1.0


# --------------------------------------------------------- constraint probe

TRUTH_TABLE = {
    "merges": [[[0, 0], [0, 1]]],
    "fills": {"9DC3E6": [[1, 1]], "D9D9D9": [[2, 1]]},
}
FULL_VIEW = {
    "merges": [[[0, 0], [0, 1]]],
    "fills": {"9DC3E6": [[1, 1]], "D9D9D9": [[2, 1]]},
    "comment_texts": ["Blue cells only."],
}


def test_constraint_probe_stays_quiet_when_everything_survives():
    assert constraint_probe(FULL_VIEW, TRUTH_TABLE, "Blue cells only.") == []


def test_constraint_probe_flags_dropped_shading():
    view = dict(FULL_VIEW, fills={"D9D9D9": [[2, 1]]})  # blue fill destroyed
    missing = constraint_probe(view, TRUTH_TABLE, "Blue cells only.")
    assert missing == ["fill 9DC3E6 at [1, 1] not recoverable"]


def test_constraint_probe_flags_dropped_merge_and_comment():
    view = dict(FULL_VIEW, merges=[], comment_texts=[])
    missing = constraint_probe(view, TRUTH_TABLE, "Blue cells only.")
    assert "merge [[0, 0], [0, 1]]-[[0, 1]]" not in missing  # exact wording below
    assert any(m.startswith("merge") for m in missing)
    assert "comment anchor not recoverable" in missing


# ------------------------------------------------------------ reading order


def test_reading_order_scorer():
    assert reading_order_ok("RO-01 x RO-02 y RO-03", ["RO-01", "RO-02", "RO-03"])
    assert not reading_order_ok("RO-02 y RO-01 x RO-03", ["RO-01", "RO-02", "RO-03"])
    assert not reading_order_ok("RO-01 x RO-03", ["RO-01", "RO-02", "RO-03"])


def test_p95_is_the_tail_not_the_mean():
    # nearest-rank: ceil(0.95 * 20) = 19th of 20 → the 50.0, mean ≈ 6.4
    assert p95([1.0] * 18 + [50.0, 60.0]) == 50.0
    assert p95([2.0]) == 2.0
    assert p95([]) == 0.0


# ------------------------------------------------------------ kill criteria


def _clean_measures(**overrides) -> dict:
    measures = {
        "cell_accuracy": {
            "complex": {"correct": 40, "total": 42, "accuracy": 40 / 42},
            "simple": {"correct": 12, "total": 12, "accuracy": 1.0},
        },
        "section_boundaries": {"checked": 12, "missed": []},
        "fabrication": {
            "tables_diffed": 4,
            "two_path_diffs": [],
            "deterministic_findings": [],
            "vlm_findings": [],
        },
        "constraint_detail": {"missing": []},
        "throughput": {"p95_s_per_page": 2.1},
    }
    measures.update(overrides)
    return measures


VM_VENUE = {"vm": True}


def test_clean_measures_pass():
    out = evaluate_kill_criteria(_clean_measures(), VM_VENUE)
    assert out["verdict"] == "pass"
    assert not out["vlm_mode_killed"]
    assert [c["verdict"] for c in out["criteria"]] == ["pass"] * 5


@pytest.mark.parametrize(
    "overrides",
    [
        {"cell_accuracy": {"complex": {"correct": 30, "total": 42, "accuracy": 30 / 42},
                           "simple": {"correct": 12, "total": 12, "accuracy": 1.0}}},
        {"section_boundaries": {"checked": 12, "missed": ["2.1 Validation Strategy"]}},
        {"fabrication": {"tables_diffed": 4, "two_path_diffs": [],
                         "deterministic_findings": [{"row": 1, "col": 1, "text": "999"}],
                         "vlm_findings": []}},
        {"constraint_detail": {"missing": ["fill 9DC3E6 at [1, 1] not recoverable"]}},
        {"throughput": {"p95_s_per_page": P95_BAR_S_PER_PAGE * 2.0 + 5}},
    ],
    ids=["complex-accuracy", "boundary-missed", "deterministic-fabrication",
         "constraint-destroyed", "p95-wide-miss"],
)
def test_kill_criteria_evaluate_a_failing_report_as_reject(overrides):
    """Each §A2.4 criterion, violated alone, renders reject — the gate
    cannot be a formality."""
    out = evaluate_kill_criteria(_clean_measures(**overrides), VM_VENUE)
    assert out["verdict"] == "reject"


def test_near_bar_p95_holds_on_a_vm_venue_instead_of_killing():
    """B51: Docker-on-Intel-Mac VM overhead cannot render a kill verdict
    near the bar — the A5 same-image re-run decides. A wide miss stands,
    and the same near-bar number on real hardware kills."""
    near = _clean_measures(throughput={"p95_s_per_page": P95_BAR_S_PER_PAGE + 1.2})
    assert evaluate_kill_criteria(near, {"vm": True})["verdict"] == "hold"
    assert evaluate_kill_criteria(near, {"vm": False})["verdict"] == "reject"


def test_vlm_fabrication_kills_only_that_mode():
    measures = _clean_measures(
        fabrication={"tables_diffed": 4, "two_path_diffs": [{"row": 0, "col": 0}],
                     "deterministic_findings": [],
                     "vlm_findings": [{"row": 0, "col": 0, "text": "invented"}]}
    )
    out = evaluate_kill_criteria(measures, VM_VENUE)
    assert out["verdict"] == "pass"
    assert out["vlm_mode_killed"] is True


def test_the_complex_bar_is_the_spec_value():
    assert CELL_ACCURACY_BAR == 0.90  # spec L65; moving it requires the owner
