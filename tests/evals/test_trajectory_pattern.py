"""P0-9 clause 2's inputs (P26a Group E): the trajectory lane measures the
engine's call pattern on the CI slice — cost and agent calls per drafted
section, deterministic under FakeCaller — so a release-to-release
compare has real numbers to move."""

from engine.evals.run import trajectory_lane
from engine.evals.trajectory import slice_call_pattern


def test_the_slice_call_pattern_is_measured_and_deterministic(tmp_path):
    first = slice_call_pattern(tmp_path / "a")
    assert first["status"] == "ok", first
    assert first["drafted_sections"] > 0 and first["agent_calls"] > 0
    assert first["cost_per_section"] > 0
    assert first["tool_calls_per_section"] >= 1
    second = slice_call_pattern(tmp_path / "b")
    assert (second["cost_per_section"], second["tool_calls_per_section"]) \
        == (first["cost_per_section"], first["tool_calls_per_section"])


def test_the_lane_carries_the_clause_two_measures():
    lane = trajectory_lane()
    assert {"cost_per_section", "tool_calls_per_section"} <= set(
        lane["measures"])
    assert lane["basis"] == "deterministic"
