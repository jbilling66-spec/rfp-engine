"""In-place firm-template fill acceptance (P17/C9, B73§2 closed):
replacement-not-insertion — drafted section prose takes the guidance
box's place AND the placeholder table goes too (the v1 gap fixed);
unanswered sections keep their guidance IDENTICAL; grids, case blocks,
the metadata table, and the inline bracketed line are recorded
fill_by_hand (B75§1e); the stream-diff verifier refuses any drift
outside the declared change set; and the template is only ever filled
at the exact digest the frozen plan was built against.

Workspaces are hand-built through the real seams (the P16
tests/assembly precedent): slots via the real parser + merge, the plan
and envelope as raw artifacts the engine reads without re-validating.
"""

import hashlib
import json
import shutil

import pytest
from docx import Document

from engine.assembly.template_fill import (
    OUTPUT_NAME,
    _assert_fill_roundtrip,
    preview_template_fill,
    run_template_fill,
)
from engine.contracts import ContractError
from engine.llm import effective_config
from engine.planning.plan import REFERENCE_DEFAULT
from engine.runlog import RunLogger, read_run
from engine.structure import merge_parsed, parse_default_template
from engine.version import engine_version
from engine.workspace import PursuitDir
from tests.helpers import plant_freeze

AT = "2026-08-29T12:00:00Z"
PARA_ONE = "First paragraph of the summary."
PARA_TWO = "Second paragraph, still synthetic."


def _workspace(tmp_path, *, ref_sha=None, source_mode=None):
    pursuit = PursuitDir(tmp_path, "pur_fill")
    parsed = parse_default_template(REFERENCE_DEFAULT)
    container = {"pursuit_id": "pur_fill", **merge_parsed([parsed])}
    if source_mode:
        container["source_mode"] = source_mode
        (pursuit.root / "slots.json").write_text(json.dumps(container))
    else:
        pursuit.write_artifact("target_slots", container, name="slots.json")
    pursuit.checkpoint("path_b_outline", {
        "reference_sha256": ref_sha or hashlib.sha256(
            REFERENCE_DEFAULT.read_bytes()).hexdigest()})
    sections = [{"section_id": f"sec-{slot}",
                 "slot_ids": [f"{slot}-hdr", slot]}
                for slot in ("s-h02", "s-h03", "s-h04")]
    plant_freeze(pursuit, "pursuit_plan", {
        "pursuit_id": "pur_fill", "path": "B_free_flow",
        "slots_ref": "slots.json", "status": "approved",
        "sections": sections})
    (pursuit.root / "drafts" / "draft.json").write_text(json.dumps({
        "plan_sha256": "0" * 64, "revision_n": 0,
        "sections": [
            {"section_id": "sec-s-h02", "status": "drafted",
             "prose": f"{PARA_ONE}\n\n{PARA_TWO}"},
            {"section_id": "sec-s-h03", "status": "drafted",
             "prose": "One firm paragraph."},
            {"section_id": "sec-s-h04", "status": "awaiting_disposition"},
        ]}))
    return pursuit


def _log(pursuit):
    log = RunLogger(pursuit.root, pursuit.new_run_id(), pursuit.pursuit_id)
    log.run_start(mode="dry_run", engine_version=engine_version(),
                  config=effective_config(), kb_snapshot="kb@empty")
    return log


def test_fill_replaces_guidance_removes_placeholder_and_reports(tmp_path):
    """THE acceptance arc: filled sections lose guidance AND placeholder,
    the delivered paragraphs land, everything else survives identical,
    the facts record every template slot exactly once, and the filled
    document still parses."""
    pursuit = _workspace(tmp_path)
    facts = preview_template_fill(pursuit, at=AT)
    assert facts["confirmed_by"] == "(unconfirmed)"
    decisions = {r["slot_id"]: r["decision"] for r in facts["sections"]}
    assert decisions["s-h02"] == "filled"
    assert decisions["s-h03"] == "filled"
    assert decisions["s-h04"] == "kept_guidance"
    assert decisions["s-h01"] == "refused_unnamed"
    assert {decisions[s] for s in
            ("s-front-meta", "s-h10", "s-h11", "s-h12-1")} \
        == {"fill_by_hand"}
    filled_rows = [r for r in facts["sections"]
                   if r["decision"] == "filled"]
    assert all(r["placeholder_removed"] for r in filled_rows)
    assert next(r for r in filled_rows
                if r["slot_id"] == "s-h02")["paragraphs"] == 2

    log = _log(pursuit)
    out = run_template_fill(pursuit, log, confirmed_by="Pat Lead", at=AT)
    log.run_end(status="completed")
    assert out["confirmed_by"] == "Pat Lead"

    doc = Document(str(pursuit.root / OUTPUT_NAME))
    texts = [p.text for p in doc.paragraphs]
    assert PARA_ONE in texts and PARA_TWO in texts
    assert texts.index(PARA_TWO) == texts.index(PARA_ONE) + 1, \
        "multi-paragraph prose stays multi-paragraph, in order"
    firsts = [t.rows[0].cells[0].text.strip() for t in doc.tables]
    guidance_left = [t for t in firsts if t.startswith("▸")]
    placeholders_left = [t for t in firsts if t.startswith("[ Replace")]
    assert len(guidance_left) == 12   # 14 sections − 2 filled
    assert len(placeholders_left) == 10  # 12 prose placeholders − 2
    assert len(out["remaining_guidance"]) == 12
    assert not any("executive summary" in g.lower()
                   for g in out["remaining_guidance"])

    # The template at config/ is never mutated, and the output reparses.
    assert hashlib.sha256(REFERENCE_DEFAULT.read_bytes()).hexdigest() \
        == out["template_sha256"]
    reparsed = parse_default_template(pursuit.root / OUTPUT_NAME)
    assert reparsed.slot_count == 29  # 31 − the two consumed prose slots

    # The facts artifact is on the run log with its digest.
    artifacts = [r for r in read_run(pursuit.root / "runs" / log.run_id /
                                     "run.jsonl")
                 if r["record_type"] == "artifact"]
    kinds = {a["artifact"]["kind"] for a in artifacts}
    assert {"template_fill_facts", "export"} <= kinds


def test_verifier_refuses_an_off_target_mutation(tmp_path):
    """The negative proof: a document differing anywhere outside the
    declared change set is refused, never handed back."""
    pursuit = _workspace(tmp_path)
    tampered = pursuit.root / "exports" / "submission" / "tampered.docx"
    tampered.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(REFERENCE_DEFAULT, tampered)
    doc = Document(str(tampered))
    victim = next(p for p in doc.paragraphs if p.text.strip())
    victim.text = victim.text + " [drifted]"
    doc.save(str(tampered))
    with pytest.raises(ContractError, match="drifted outside"):
        _assert_fill_roundtrip(REFERENCE_DEFAULT, tampered, {})


def test_template_drift_since_planning_refuses(tmp_path):
    pursuit = _workspace(tmp_path, ref_sha="0" * 64)
    with pytest.raises(ContractError, match="drifted since planning"):
        preview_template_fill(pursuit, at=AT)


def test_buyer_containers_refuse_this_lane(tmp_path):
    pursuit = _workspace(tmp_path, source_mode="client_provided")
    with pytest.raises(ContractError, match="firm_default lane"):
        preview_template_fill(pursuit, at=AT)
