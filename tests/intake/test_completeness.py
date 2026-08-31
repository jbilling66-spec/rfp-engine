"""Completeness: every miss is a gap record, never a silent hole — and
every field P3 claims to write is actually written somewhere (the B11
field-with-no-writer class, tested)."""

import json

from engine.contracts import validate
from engine.runlog import read_run
from tests.intake.fixtures.packages import RAMBLE, _wire_from_prompt, run_package


def test_starved_wire_gaps_with_reasons_brief_still_writes(tmp_path):
    def starving(prompt: str) -> str:
        wire = json.loads(_wire_from_prompt(prompt))
        wire["procurement"].pop("what_is_bought", None)
        wire["procurement"].pop("deadlines", None)
        return json.dumps(wire)

    pursuit, report = run_package(tmp_path, "pdf", script={"intake_analyst": starving})
    assert report.status == "incomplete"
    targets = {m["target"] for m in report.misses}
    assert "procurement.what_is_bought" in targets
    assert "procurement.deadlines" in targets  # date candidates existed, none extracted

    records = read_run(pursuit.root / "runs" / "run_0001" / "run.jsonl")
    gaps = [r["gap"] for r in records if r["record_type"] == "gap"]
    assert len(gaps) == len(report.misses)
    for gap in gaps:
        assert gap["reason"] in {"kb_empty", "stale_fact", "needs_sme",
                                 "partner_only", "not_offered", "ambiguous_requirement"}
        assert gap["resolution"] == "unresolved"
        assert gap["question_to_human"]

    # the brief still landed, valid, as a draft — incomplete is honest, not fatal
    brief = pursuit.read_artifact("brief.json")
    validate("bid_brief", brief)
    assert brief["status"] == "draft"


def test_stripped_weights_miss_as_ambiguous_requirement(tmp_path):
    def unweighted(prompt: str) -> str:
        wire = json.loads(_wire_from_prompt(prompt))
        for row in wire["requirements"]:
            row.pop("weight_text", None)
        return json.dumps(wire)

    _, report = run_package(tmp_path, "pdf", script={"intake_analyst": unweighted})
    assert report.status == "incomplete"
    weight_misses = [m for m in report.misses if m["target"] == "requirements_matrix.weight"]
    assert len(weight_misses) == 1
    assert weight_misses[0]["reason"] == "ambiguous_requirement"


def test_bare_cell_weights_are_stated_weights():
    """B67-F1, fixed here (P15/C3): the first real buyer RFP stated all
    seven of its evaluation weights as BARE CELLS in a criteria table —
    the old regex matched only '(30%)' / ': 40%', so the brief reported
    complete on weights it never found. Silent miss, not a gap. The text
    below reproduces the SHAPE (synthetic content): pipe-bounded cells
    the way the extractors render tables, plus a percent-alone line the
    way a pdf table column falls out — including a duplicated 15%,
    because the old set-dedup counted two same-valued criteria once."""
    from engine.intake.brief import _stated_weight_values
    from engine.intake.extract import ExtractedDoc

    doc = ExtractedDoc(file="criteria.xlsx", format="xlsx", text=(
        "| Selection Criteria | Details | Scoring Weights |\n"
        "| Platform Capabilities | vendor manages technology | 5% |\n"
        "| Industry Expertise | depth of process knowledge | 15% |\n"
        "| Delivery Excellence | tools and methodology | 15% |\n"
        "| Product Expertise | reporting requirements | 45% |\n"
        "[page 9]\n"
        "Technology Enablement\n"
        "10%\n"
        "Uptime of 95% is required during business hours.\n"))
    stated = _stated_weight_values([doc])
    assert sorted(stated) == ["10%", "15%", "15%", "45%", "5%"]
    # the prose percent did NOT match — the standing docstring rule holds
    assert "95%" not in stated


def test_gaps_persist_on_the_brief_mirroring_the_log(tmp_path):
    """P15/C4: the intake questions land on the ARTIFACT, not only the
    run log — a log line alone can never be answered (the ping lane
    joins artifacts), which is how every intake question died unresolved
    before this phase. Same ids, same reasons, open, origin=completeness."""
    def starving(prompt: str) -> str:
        wire = json.loads(_wire_from_prompt(prompt))
        wire["procurement"].pop("what_is_bought", None)
        return json.dumps(wire)

    pursuit, report = run_package(
        tmp_path, "pdf", script={"intake_analyst": starving})
    brief = pursuit.read_artifact("brief.json")
    validate("bid_brief", brief)
    gaps = brief["intake"]["gaps"]
    assert len(gaps) == len(report.misses) > 0
    records = read_run(pursuit.root / "runs" / "run_0001" / "run.jsonl")
    logged = {r["gap"]["gap_id"]: r["gap"] for r in records
              if r["record_type"] == "gap"}
    for gap in gaps:
        assert gap["status"] == "open"
        assert gap["origin"] == "completeness"
        assert gap["target"]
        twin = logged[gap["gap_id"]]
        assert twin["reason"] == gap["reason"]
        assert twin["question_to_human"] == gap["question_to_human"]


def test_assumption_register_lists_model_inferences_with_provenance(tmp_path):
    """P15/C4: every structured model inference is on the register,
    unconfirmed, and the code-parsed values ride along as source=code —
    a confident-but-wrong inference must announce itself at gate_0."""
    pursuit, _ = run_package(tmp_path, "pdf", ramble=RAMBLE)
    brief = pursuit.read_artifact("brief.json")
    validate("bid_brief", brief)
    register = brief["intake"]["assumptions"]
    by_field = {e["field"]: e for e in register}

    for field in ("buyer.name", "procurement.what_is_bought",
                  "procurement.response_structure"):
        assert by_field[field]["source"] == "model"
        assert by_field[field]["value"] == _get(brief, field)
    weight_entries = [e for e in register
                      if e["field"].endswith(".weight")]
    assert weight_entries and all(
        e["source"] == "code" for e in weight_entries)
    assert all(e["status"] == "unconfirmed" for e in register)
    # prose fields are deliberately absent — a register that lists
    # everything teaches its reader to confirm nothing
    assert "buyer.profile" not in by_field


def _get(brief: dict, dotted: str):
    node = brief
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def test_every_claimed_field_has_a_writer(tmp_path):
    """v1 shipped eval_weight with no writer for its whole life (and v2's
    B11 was the same class). Every brief field P3 claims must be
    non-trivially present across the two acceptance packages."""
    briefs = [
        run_package(tmp_path / "x", "xlsx", ramble=RAMBLE)[0].read_artifact("brief.json"),
        run_package(tmp_path / "p", "pdf", ramble=RAMBLE)[0].read_artifact("brief.json"),
    ]
    claimed = [
        "pursuit_id", "status",
        "intake.documents", "intake.ramble_context",
        "intake.assumptions",  # P15/C4 — the register writes on every run
        "buyer.name", "buyer.vertical", "buyer.profile", "buyer.terminology",
        "buyer.incumbent",
        "procurement.what_is_bought", "procurement.response_structure",
        "procurement.deadlines", "procurement.required_forms",
        "procurement.submission_method", "procurement.red_flags",
        "requirements_matrix",
    ]
    for dotted in claimed:
        values = [_get(b, dotted) for b in briefs]
        assert any(v not in (None, "", [], {}) for v in values), (
            f"{dotted}: claimed by P3 but written by nothing (B11 class)"
        )
    rows = [row for b in briefs for row in b["requirements_matrix"]]
    for key in ("ref", "requirement", "section", "weight", "weight_basis",
                "weight_text", "mandatory"):
        assert any(key in row for row in rows), f"matrix.{key} has no writer"
    flags = [f for b in briefs for f in b["procurement"]["red_flags"]]
    for key in ("kind", "detail", "excerpt", "source_location", "detected_by", "routed_to"):
        assert any(key in f for f in flags), f"red_flags.{key} has no writer"
