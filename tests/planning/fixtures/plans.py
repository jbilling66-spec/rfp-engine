"""Planning test harness: the P5 chain extended one stage (run_0004).

run_planning_package chains intake -> KB -> research -> strategy ->
Gate 1 (approved) -> planning, with the manifest (and reference, when
present) digest-folded into config via effective_config(extra=...) —
B16's "manifest becomes a run variable" closure.

make_architect_script is the derive-wire-from-prompt fake (house
pattern #1): it reads the reference and brief frames the stage actually
inlined and emits an ADAPTATION — merge, reorder, buyer-specific
addition, themes threaded — so fixture, prompt, frame, and script
cannot drift, and every based_on/theme/ref is real by construction.
The frame regexes here are the single source test_plan_frames asserts
against engine.llm.frames.

write_prior_plan builds a minimal schema-valid APPROVED sibling plan
through the REAL seams (write_artifact + write_json + per-slot
validate) — the cheap honest prior for precedent tests.
"""

import hashlib
import json
import re
from pathlib import Path

from engine.contracts import validate
from engine.kb import KBStore
from engine.llm import FakeCaller, TracedCaller, effective_config
from engine.planning import run_planning
from engine.planning.plan import MANIFEST_DEFAULT, REFERENCE_DEFAULT
from engine.runlog import RunLogger
from engine.version import engine_version
from engine.workspace import PursuitDir
from tests.strategy.fixtures.strategies import run_strategy_package

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"

GATE2_AT = "2026-08-02T12:00:00Z"
ACTOR = "test_pursuit_lead"

# The workbook each designated package's plan is built from.
WORKBOOKS = {
    "xlsx": "structured-twin.xlsx",
    "nofill": "nofill-twin.xlsx",
    "gapcase": "gapcase-twin.xlsx",
}


def planning_extras(manifest_path: Path = MANIFEST_DEFAULT,
                    reference_path: Path = REFERENCE_DEFAULT) -> dict:
    """The planning run variables, digest-visible (B16/B27): two runs are
    comparable only when manifest and reference content match."""
    extras: dict = {"planning": {
        "manifest_sha256": hashlib.sha256(
            Path(manifest_path).read_bytes()
        ).hexdigest(),
    }}
    reference_path = Path(reference_path)
    if reference_path.is_file():
        extras["planning"]["reference_sha256"] = hashlib.sha256(
            reference_path.read_bytes()
        ).hexdigest()
    return extras


def run_planning_package(tmp_root, *, package_id="xlsx", workbook=None,
                         script=None, gate2="approved", edits=None,
                         notes=None, actor=ACTOR, at=GATE2_AT):
    """Full chain to a plan (and optionally through Gate 2). gate2=None
    stops before the gate (run ends awaiting_gate); a refused planning
    stage still closes the run."""
    pursuit, _ = run_strategy_package(tmp_root, package_id=package_id)
    store = KBStore(tmp_root / "kb")  # reopened from disk (resume precedent)
    log = RunLogger(pursuit.root, pursuit.new_run_id(), pursuit.pursuit_id)
    caller = TracedCaller(FakeCaller(script or make_architect_script()), log)
    cfg = effective_config(extra=planning_extras())
    log.run_start(mode="dry_run", engine_version=engine_version(), config=cfg,
                  kb_snapshot=store.snapshot(),
                  research_mode=cfg["research_mode"])
    if workbook is None:
        name = WORKBOOKS.get(package_id)
        workbook = FIXTURES / name if name else None
    report = run_planning(pursuit, caller, log, store, workbook=workbook)
    if gate2 is None or report.status == "refused":
        log.run_end(status="awaiting_gate" if report.status == "complete"
                    else "completed")
        return pursuit, report
    from engine.planning import approve_gate2
    approve_gate2(pursuit, log, decision=gate2, actor=actor, at=at,
                  notes=notes, edits=edits)
    log.run_end(status="completed")
    return pursuit, report


# Frame regexes — single source for the derive-wire script AND the
# frame-drift assertions in test_plan_frames (strategies.py precedent).
REFERENCE_RX = re.compile(
    r'<firm_reference label="firm">\n(.*?)\n</firm_reference>', re.S
)
BRIEF_RX = re.compile(
    r'<bid_brief_context label="semi_trusted">\n(.*?)\n</bid_brief_context>',
    re.S,
)
LEAD_RX = re.compile(
    r'<pursuit_lead_context label="firm">\n(.*?)\n</pursuit_lead_context>',
    re.S,
)
_REF_LINE_RX = re.compile(r"^- ([a-z0-9-]+) \| ([^|]+) \| (.+)$", re.M)
_THEME_LINE_RX = re.compile(r"^\* (.+)$", re.M)
_MATRIX_LINE_RX = re.compile(r"^- (\S+) \| (.+)$", re.M)
_TERMS_RX = re.compile(r"^Buyer terminology: (.+)$", re.M)
_QUOTED_RX = re.compile(r'"([^"]+)"')


def make_architect_script(*, plant_unknown_theme=False, plant_bad_ref=False,
                          plant_bad_source=False, plant_unknown_based_on=False,
                          empty_sections=False, drop_title=False):
    """The well-behaved architect fake, with plantable misbehaviors. The
    emitted outline ADAPTS the reference it reads back: understanding
    moves ahead of the executive summary (reorder), company overview and
    experience merge (based_on x2), and a buyer-specific section is
    added from the first buyer-terminology term. When rejection feedback
    is present, a section titled from its first quoted phrase is added —
    the redo provably differs from round one."""

    def _outline(prompt: str) -> str:
        if empty_sections:
            return json.dumps({"sections": []})
        reference = REFERENCE_RX.search(prompt).group(1)
        ref_ids = [m.group(1) for m in _REF_LINE_RX.finditer(reference)]
        brief = BRIEF_RX.search(prompt).group(1)
        themes = [m.group(1) for m in _THEME_LINE_RX.finditer(brief)]
        matrix_refs = [m.group(1) for m in _MATRIX_LINE_RX.finditer(brief)
                       if m.group(1) != "(no" and "." in m.group(1)]
        terms_match = _TERMS_RX.search(brief)
        first_term = (terms_match.group(1).split(";")[0].strip()
                      if terms_match else "the engagement")

        def based(*prefixes):
            # ids are read back from the frame (truncation-proof): match
            # by prefix so the script never hardcodes slug lengths.
            return [next(i for i in ref_ids if i.startswith(p))
                    for p in prefixes]

        sections = [
            {"title": "Cover Letter", "purpose": "Open with the buyer's objective.",
             "source": "firm_reference", "based_on": based("cover-letter")},
            {"title": "Understanding of Needs",
             "purpose": "The buyer's goals in their own terminology.",
             "source": "firm_reference", "based_on": based("understanding-of")},
            {"title": "Executive Summary",
             "purpose": "Need, solution, outcomes, themes threaded.",
             "source": "firm_reference", "based_on": based("executive-summary"),
             "win_themes": list(themes)},
            {"title": "Solution and Delivery Approach",
             "purpose": "How each stated requirement is met and delivered.",
             "source": "firm_reference",
             "based_on": based("proposed-solution",
                               "implementation-methodology"),
             "requirement_refs": matrix_refs[:1]},
            {"title": "Firm Experience and Credentials",
             "purpose": "Credentials and case studies merged for this buyer.",
             "source": "firm_reference",
             "based_on": based("company-overview", "relevant-experience")},
            {"title": f"Approach to the {first_term}",
             "purpose": "Buyer-specific section for the platform scope.",
             "source": "architect_added",
             "requirement_refs": matrix_refs[1:2],
             "win_themes": list(themes)},
        ]
        lead = LEAD_RX.search(prompt)
        if lead:
            quoted = _QUOTED_RX.search(lead.group(1))
            if quoted:
                sections.append({
                    "title": quoted.group(1),
                    "purpose": "Added on pursuit-lead feedback after Gate-2 "
                               "rejection.",
                    "source": "architect_added",
                })
        if plant_unknown_theme:
            sections[2]["win_themes"] = list(themes) + [
                "Invented theme nobody approved"
            ]
        if plant_bad_ref:
            sections[3]["requirement_refs"] = (
                sections[3].get("requirement_refs", []) + ["9.9"]
            )
        if plant_bad_source:
            sections[5]["source"] = "buyer_structure"
        if plant_unknown_based_on:
            sections[0]["based_on"] = sections[0]["based_on"] + ["no-such-id"]
        if drop_title:
            del sections[0]["title"]
        return json.dumps({"sections": sections})

    def _dispatch(prompt: str) -> str:
        _dispatch.prompts.append(prompt)
        return _outline(prompt)

    _dispatch.prompts = []
    return {"outline_architect": _dispatch}


ARCHITECT_SCRIPT = make_architect_script()


def open_gate_run(tmp_root, pursuit):
    """A fresh, properly-opened run for a standalone gate decision —
    gate lines never append after a closed run's footer (P5 lesson)."""
    store = KBStore(tmp_root / "kb")
    log = RunLogger(pursuit.root, pursuit.new_run_id(), pursuit.pursuit_id)
    cfg = effective_config(extra=planning_extras())
    log.run_start(mode="dry_run", engine_version=engine_version(), config=cfg,
                  kb_snapshot=store.snapshot(),
                  research_mode=cfg["research_mode"])
    return log


def write_prior_plan(tmp_root, *, pursuit_id="pur_prior", question_text=None,
                     section_title="Prior Section", kb_ids=("kb-prior-1",),
                     status="approved"):
    """A minimal valid sibling plan, written through the real seams so
    the precedent scan reads exactly what production would."""
    prior = PursuitDir(tmp_root, pursuit_id)
    section = {
        "section_id": "prior-section",
        "title": section_title,
        "source": "client_structure",
        "kb_hits": [{"kb_id": kb_id} for kb_id in kb_ids],
    }
    plan = {
        "pursuit_id": pursuit_id,
        "path": "A_designated",
        "sections": [section],
        "status": status,
    }
    if question_text is not None:
        slot = {
            "slot_id": "slot_00_r002",
            "source_mode": "client_provided",
            "response_shape": "prose",
            "question_text": question_text,
        }
        validate("target_slot", slot)
        prior.write_json("slots.json", {
            "pursuit_id": pursuit_id,
            "source_mode": "client_provided",
            "parser_version": "2.0.0",
            "source_sha256": "0" * 64,
            "slot_count": 1,
            "slots": [slot],
        })
        section["slot_ids"] = ["slot_00_r002"]
        plan["slots_ref"] = "slots.json"
    prior.write_artifact("pursuit_plan", plan)
    return prior
