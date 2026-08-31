"""effort_allocation (c22) — B33(3)'s pin closed.

The field was schema-declared with a documented default and no writer,
so every plan claimed "uniform" by omission. Writing it makes the choice
inspectable, and the condition is the honest one: depth follows weights
only where a buyer supplied weights to follow. Inventing a weighting
from an unweighted matrix would be the engine deciding what the buyer
cares about.

The plan-contract pin is BIDIRECTIONAL — leaving effort_allocation in
NOT_YET_WRITTEN after the writer landed fails just as loudly as adding a
field with no writer, which is why the pin removal ships in this commit.
"""

from engine.drafting.compose import section_directive
from engine.planning.plan import _effort_allocation

SECTION = {"section_id": "s1", "title": "Implementation Methodology",
           "requirement_refs": ["2.0.1", "2.0.5"]}


def test_a_weighted_matrix_writes_weighted():
    frozen = {"requirements_matrix": [
        {"ref": "2.0.1", "requirement": "Methodology", "weight": 30.0},
        {"ref": "2.0.5", "requirement": "Team"},
    ]}
    assert _effort_allocation(frozen) == "weighted"


def test_an_unweighted_matrix_writes_uniform_explicitly():
    frozen = {"requirements_matrix": [
        {"ref": "1.1", "requirement": "Describe your approach"},
    ]}
    assert _effort_allocation(frozen) == "uniform"


def test_no_matrix_at_all_is_uniform_not_a_crash():
    assert _effort_allocation({}) == "uniform"


def test_the_drafter_consumes_it_and_says_which_refs_are_scored():
    """A field nobody reads is a field that means nothing."""
    weighted = section_directive(
        SECTION, [], canonical_ids=[], flagged_slot_ids=[],
        flag_section=False, path="B_free_flow",
        effort_allocation="weighted")
    assert "WEIGHTED" in weighted
    assert "2.0.1" in weighted, "the refs the buyer scores are named"


def test_uniform_adds_nothing_to_the_prompt():
    """The default must be byte-identical to the pre-P10 directive, or
    every existing golden moves for a plan that chose nothing."""
    uniform = section_directive(
        SECTION, [], canonical_ids=[], flagged_slot_ids=[],
        flag_section=False, path="B_free_flow",
        effort_allocation="uniform")
    default = section_directive(
        SECTION, [], canonical_ids=[], flagged_slot_ids=[],
        flag_section=False, path="B_free_flow")
    assert uniform == default
    assert "WEIGHTED" not in uniform


def test_weighting_never_overrules_a_slots_own_limit():
    """The emphasis line says WHICH refs are scored and leaves depth to
    the drafter. A length instruction here would let the plan quietly
    overrule the slot's word limit — the buyer's constraint wins."""
    weighted = section_directive(
        SECTION, [], canonical_ids=[], flagged_slot_ids=[],
        flag_section=False, path="B_free_flow",
        effort_allocation="weighted")
    lowered = weighted.lower()
    for forbidden in ("words", "longer", "expand to", "at least"):
        assert forbidden not in lowered


def test_a_weighted_section_with_no_refs_adds_nothing():
    """Weighting is per-section evidence, not a global volume knob."""
    bare = section_directive(
        {"section_id": "s2", "title": "Appendix"}, [], canonical_ids=[],
        flagged_slot_ids=[], flag_section=False, path="B_free_flow",
        effort_allocation="weighted")
    assert "WEIGHTED" not in bare


def test_the_contract_pin_no_longer_claims_it_is_unwritten():
    from tests.planning.test_plan_contract import NOT_YET_WRITTEN

    assert "effort_allocation" not in NOT_YET_WRITTEN, (
        "the pin is bidirectional: a written field left pinned fails as "
        "loudly as an unwritten field left unpinned")
