"""Path-B acceptance: the outline visibly ADAPTS the reference (merge,
reorder, buyer-specific addition), themes thread code-gated, and every
wire gate drops-and-reports. The adaptation grammar mirrors the owner's own
worked exemplar: sections merged and reordered, a buyer-specific
section added, win themes threaded."""

import json

import pytest

from engine.contracts import ContractError
from engine.llm.frames import wrap_brief_context, wrap_reference
from engine.planning.outline import brief_digest, parse_wire_outline
from engine.planning.plan import REFERENCE_DEFAULT
from engine.planning.reference import load_reference, render_reference
from engine.runlog import read_run
from tests.planning.fixtures.plans import (
    make_architect_script,
    run_planning_package,
    write_prior_plan,
)


@pytest.fixture(scope="module")
def planned(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("plan-path-b")
    # A prior approved plan whose section title matches the outline's —
    # the Path-B (title-keyed) precedent case rides this chain.
    write_prior_plan(tmp, pursuit_id="pur_prior_b",
                     section_title="Executive Summary",
                     kb_ids=("kb-prior-exec",))
    script = make_architect_script()
    pursuit, report = run_planning_package(tmp, package_id="pdf",
                                           script=script, gate2=None)
    return pursuit, report, script


def test_outline_merges_reorders_and_adds(planned):
    pursuit, report, _ = planned
    assert report.status == "complete" and report.path == "B_free_flow"
    plan = pursuit.read_artifact("plan.json")
    # P16/C7: free-form routes to the FIRM TEMPLATE — Path B now carries
    # the template's parsed slots instead of an invented bare outline.
    assert plan["slots_ref"] == "slots.json"
    container = pursuit.read_artifact("slots.json")
    assert container["source_mode"] == "firm_default"
    assert container["slot_count"] > 0
    # Adaptation provenance rides the plan itself since E1 (the artifact,
    # not a checkpoint, carries the record).
    based_on = {s["section_id"]: s.get("based_on", [])
                for s in plan["sections"]}

    # MERGE: one section absorbs two reference sections.
    merged = [sid for sid, ids in based_on.items() if len(ids) >= 2]
    assert "firm-experience-and-credential" in merged

    # REORDER: understanding precedes the executive summary in the plan;
    # the reference orders them the other way.
    order = [s["section_id"] for s in plan["sections"]]
    assert order.index("understanding-of-needs") < order.index("executive-summary")
    reference_ids = load_reference(REFERENCE_DEFAULT).ids()
    assert reference_ids.index("executive-summary") < reference_ids.index(
        "understanding-of-your-requirem"
    )

    # ADD: a buyer-specific section, mirroring the buyer's own
    # terminology from the frozen brief.
    added = [s for s in plan["sections"] if s["source"] == "architect_added"]
    assert len(added) == 1
    terminology = pursuit.read_artifact("brief.frozen.json")["buyer"]["terminology"]
    assert terminology[0] in added[0]["title"]
    assert not based_on[added[0]["section_id"]]


def test_sections_inherit_template_slots_and_gaps_join_them(planned):
    """P16/C7: a based_on section inherits its template sections' slots
    (a merge inherits BOTH), an architect_added section keeps its
    creative freedom (no slots, grounded by title+purpose) — and the
    empty-KB gaps on slotted sections are slot-joined, so Gate 2's
    map-and-ask works for the free-form shape too."""
    pursuit, _, _ = planned
    plan = pursuit.read_artifact("plan.json")
    by_id = {s["section_id"]: s for s in plan["sections"]}

    merged = by_id["firm-experience-and-credential"]
    assert {sid.split("-")[1] for sid in merged["slot_ids"]} == {"h09", "h10"}

    added = next(s for s in plan["sections"]
                 if s["source"] == "architect_added")
    assert added["slot_ids"] == []

    # The join invariant, wherever the chain's KB left gaps: a gap on a
    # slotted section names one of ITS slots; a slotless section's gap
    # names none (section-scoped, the pre-P16 shape).
    gapped = [s for s in plan["sections"] if s.get("gaps")]
    assert gapped  # the chain's KB never grounds everything
    for section in gapped:
        for gap in section["gaps"]:
            if section["slot_ids"]:
                assert gap["slot_id"] in set(section["slot_ids"])
            else:
                assert "slot_id" not in gap


def test_win_themes_threaded_subset_of_approved(planned):
    pursuit, _, _ = planned
    plan = pursuit.read_artifact("plan.json")
    approved = set(
        pursuit.read_artifact("brief.frozen.json")["win_themes"]["approved"]
    )
    threaded = [s for s in plan["sections"] if s.get("win_themes")]
    assert threaded  # at least the executive summary
    for section in threaded:
        assert set(section["win_themes"]) <= approved
    exec_summary = next(s for s in plan["sections"]
                        if s["section_id"] == "executive-summary")
    assert set(exec_summary["win_themes"]) == approved


def test_requirement_refs_within_matrix_and_sections_mapped(planned):
    pursuit, _, _ = planned
    plan = pursuit.read_artifact("plan.json")
    matrix_refs = {
        r["ref"] for r in
        pursuit.read_artifact("brief.frozen.json")["requirements_matrix"]
        if r.get("ref")
    }
    for section in plan["sections"]:
        for ref in section.get("requirement_refs", []):
            assert ref in matrix_refs
        # Every section was honestly mapped: grounded or gapped, never
        # silently neither.
        assert ("kb_hits" in section) != ("gaps" in section)


def test_one_frontier_call_and_prompt_frames(planned):
    pursuit, _, script = planned
    records = read_run(pursuit.root / "runs" / "run_0004" / "run.jsonl")
    calls = [r for r in records if r["record_type"] == "agent_call"]
    assert [(c["agent"], c["model_tier"], c["model"]) for c in calls] == [
        ("outline_architect", "frontier", "fake-frontier-1"),
    ]
    # The captured prompt starts with the task line and carries the
    # reference frame — the derive-wire seam the redo test reads.
    assert len(script["outline_architect"].prompts) == 1
    prompt = script["outline_architect"].prompts[0]
    assert prompt.startswith("Task: outline.")
    assert '<firm_reference label="firm">' in prompt


def test_path_b_precedent_matches_on_title(planned):
    pursuit, _, _ = planned
    exec_summary = next(
        s for s in pursuit.read_artifact("plan.json")["sections"]
        if s["section_id"] == "executive-summary"
    )
    hits = [p for p in exec_summary["precedents"]
            if p["pursuit_id"] == "pur_prior_b"]
    assert len(hits) == 1
    assert hits[0]["note"] == "exact title match"
    assert hits[0]["kb_ids"] == ["kb-prior-exec"]


# --- wire-gate units (no chain needed: script -> parse, non-vacuous by
# --- construction because each planted violation is proven dropped) ----

_FROZEN = {
    "buyer": {"name": "Northwind Regional Health", "vertical": "healthcare",
              "terminology": ["integrated ERP platform"]},
    "procurement": {"what_is_bought": "ERP implementation services"},
    "win_themes": {"approved": ["Theme one", "Theme two"]},
    "requirements_matrix": [{"ref": "3.1", "requirement": "Vendor shall A."},
                            {"ref": "3.2", "requirement": "Vendor shall B."}],
}


def _wire(script) -> str:
    outline = load_reference(REFERENCE_DEFAULT)
    prompt = "\n\n".join([
        "Task: outline.",
        wrap_brief_context(brief_digest(_FROZEN)),
        wrap_reference(render_reference(outline)),
    ])
    return script["outline_architect"](prompt)


def _parse(text):
    outline = load_reference(REFERENCE_DEFAULT)
    return parse_wire_outline(
        text, reference_ids=set(outline.ids()),
        matrix_refs={"3.1", "3.2"}, approved=["Theme one", "Theme two"],
    )


def test_wire_gates_drop_and_report():
    sections, _, warnings = _parse(_wire(make_architect_script(
        plant_unknown_theme=True, plant_bad_ref=True,
        plant_bad_source=True, plant_unknown_based_on=True,
    )))
    joined = "\n".join(warnings)
    assert "Invented theme nobody approved" in joined
    assert "9.9" in joined
    assert "coerced to architect_added" in joined
    assert "no-such-id" in joined
    # Nothing planted survived into the kept sections.
    for section in sections:
        assert "Invented theme nobody approved" not in section.get("win_themes", [])
        assert "9.9" not in section.get("requirement_refs", [])
        assert section["source"] in ("firm_reference", "architect_added")


def test_entry_without_title_dropped():
    sections, _, warnings = _parse(_wire(make_architect_script(drop_title=True)))
    assert len(sections) == 5  # six emitted, the titleless one dropped
    assert any("no title" in w for w in warnings)


def test_empty_outline_raises():
    with pytest.raises(ContractError, match="no sections"):
        _parse(json.dumps({"sections": []}))
    with pytest.raises(ContractError, match="unparseable"):
        _parse("not json at all")
