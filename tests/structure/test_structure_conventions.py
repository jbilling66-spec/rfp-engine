"""Layer-2 learned conventions: what each twin teaches the parser about
itself. These pin the convention layer separately from classification so
a rule change fails at the layer that moved."""

from pathlib import Path

from engine.structure.conventions import learn_conventions
from engine.structure.facts import collect_workbook_facts

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _conv(name: str):
    return learn_conventions(collect_workbook_facts(FIXTURES / name))


def test_structured_twin_learns_fill_mode():
    conv = _conv("structured-twin.xlsx")
    assert conv.writable_fill == "FFFF00"  # the yellow answer fill
    assert conv.legend_source == "dominant"
    sheet1 = conv.sheets["1. Company Background"]
    assert sheet1.ref_col == 1 and sheet1.question_col == 2 and sheet1.answer_col == 3
    assert sheet1.leaf_depth == 3
    assert conv.sheets["2. Integration "].leaf_depth == 3  # byte-exact key
    assert conv.sheets["Instructions"].kind == "instructions"


def test_pricing_sheet_is_a_grid_and_value_rows_are_not_labels():
    conv = _conv("structured-twin.xlsx")
    pricing = conv.sheets["3. Pricing"]
    assert pricing.kind == "grid"
    # "Discover | 400" must not masquerade as a label row — a bare number
    # is data. Only the real header row labels the grid.
    assert sorted(pricing.label_rows) == [1]
    assert [label for _, label in pricing.label_rows[1]] == ["Phase", "Hours"]


def test_nofill_twin_learns_structural_mode():
    """EC-3's fix at the layer it lives in: no fills anywhere -> the
    structural fallback still votes leaf depth from dotted-ref question
    rows, and the answer column derives from the question column."""
    conv = _conv("nofill-twin.xlsx")
    assert conv.writable_fill is None
    assert conv.legend_source == "structural"
    sc = conv.sheets["Scope of Services"]
    assert sc.ref_col == 1
    assert sc.leaf_depth == 2  # 1.1-style numbering, NOT the default 3
    assert sc.answer_col == sc.question_col + 1
