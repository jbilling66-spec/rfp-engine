"""Path-A acceptance: the structured twin chains to a correct plan.

Goldens are hand-derived from the committed twin + brief chain (sheet
names, refs, matrix rows), never from parser output.
"""

import pytest

from engine.contracts import validate
from tests.planning.fixtures.plans import run_planning_package


@pytest.fixture(scope="module")
def planned(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("plan-path-a")
    pursuit, report = run_planning_package(tmp, package_id="xlsx", gate2=None)
    return pursuit, report


def test_structured_twin_plan_matches_golden(planned):
    pursuit, report = planned
    assert report.status == "complete" and report.path == "A_designated"
    plan = pursuit.read_artifact("plan.json")
    validate("pursuit_plan", plan)
    assert plan["status"] == "gate2_pending"
    assert plan["slots_ref"] == "slots.json"
    assert "created" not in plan and "gate2" not in plan  # gate stamps time

    # Hand-derived sections: three content sheets -> three sections.
    assert [(s["section_id"], s["title"]) for s in plan["sections"]] == [
        ("1-company-background", "1. Company Background"),
        ("2-integration", "2. Integration"),  # EC-1: stripped for display
        ("3-pricing", "3. Pricing"),
    ]
    company, integration, pricing = plan["sections"]
    assert company["slot_ids"] == ["slot_01_r002", "slot_01_r003", "slot_01_r004"]
    # requirement_refs join the brief matrix on the buyer's own refs;
    # the duplicate 2.0.5 dedupes, 2.0.7 is a matrix row too.
    assert company["requirement_refs"] == ["1.0.1", "1.0.2", "1.0.3"]
    assert integration["requirement_refs"] == ["2.0.1", "2.0.5", "2.0.7"]
    assert "requirement_refs" not in pricing

    # Narrative sections carry every approved theme (pinned Path-A rule);
    # the pricing grid section carries none.
    brief = pursuit.read_artifact("brief.frozen.json")
    approved = brief["win_themes"]["approved"]
    assert len(approved) == 2
    assert company["win_themes"] == approved
    assert integration["win_themes"] == approved
    assert "win_themes" not in pricing

    # Grounding: the ERP questions hit the corpus; the grid is
    # shape-skipped (listed, unmapped, ungapped — P9 owns pricing).
    assert company["kb_hits"] and integration["kb_hits"]
    for hit in company["kb_hits"]:
        assert 0 < hit["confidence"] <= 1
    assert "kb_hits" not in pricing and "gaps" not in pricing


def test_slots_container_written_and_counted(planned):
    pursuit, _ = planned
    container = pursuit.read_artifact("slots.json")
    assert container["slot_count"] == len(container["slots"]) == 8
    assert container["parser_version"] == "2.1.0"  # bumped at P26b-1 (B112)
    for slot in container["slots"]:
        validate("target_slot", slot)


def test_coverage_identity(planned):
    pursuit, _ = planned
    cov = pursuit.read_artifact("plan.json")["coverage_summary"]
    # 7 answerable prose slots; the grid is shape-skipped out of total.
    assert cov["total_requirements"] == 7
    assert cov["total_requirements"] == (
        cov["covered"] + cov["open_gaps"] + cov["omit_approved"]
        + cov["draft_flagged"]
    )


def test_plan_build_is_byte_deterministic(planned, tmp_path):
    """Two full chains, two workspaces, identical plan bytes — the
    zero-model Path-A promise made literal."""
    pursuit_a, _ = planned
    pursuit_b, _ = run_planning_package(tmp_path, package_id="xlsx", gate2=None)
    a = (pursuit_a.root / "plan.json").read_bytes()
    b = (pursuit_b.root / "plan.json").read_bytes()
    assert a == b
    assert (pursuit_a.root / "slots.json").read_bytes() == (
        pursuit_b.root / "slots.json"
    ).read_bytes()


def test_slots_container_is_contract_validated(planned):
    """E4 (B37/D23): the container graduated from write_json to a
    registered contract kind — the written container passes, and the
    validation is non-vacuous: a container missing its write-back binding
    (source_sha256) refuses to write."""
    from engine.contracts import ContractError, validate

    pursuit, _ = planned
    container = pursuit.read_artifact("slots.json")
    validate("target_slots", container)
    bad = {k: v for k, v in container.items() if k != "source_sha256"}
    with pytest.raises(ContractError):
        pursuit.write_artifact("target_slots", bad, name="slots-bad.json")
    assert not (pursuit.root / "slots-bad.json").exists()
