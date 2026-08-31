"""run_planning — the planning stage pair: path_a_map / path_b_outline
(guarded spend+emission) and pursuit_plan (replay-always assembly).

Refusal gates before any spend or write (error records, zero model
calls). Content authority for everything downstream of the fork is
brief.frozen.json (B22(9): the frozen copy is what protects planning
from a post-gate research rerun); the fork PREDICATE is checked on
brief.json (the pinned SESSION.md rule).

Gap lines are emitted ONLY in the guarded path stage and carried in its
checkpoint — pursuit_plan replays without them, so a resume never
double-counts totals.gaps_opened. No wall-clock in any stage write;
Gate 2 stamps time via injected `at`.

Rejection feedback (recorded decision, 2026-08-02): when the gate_2 checkpoint holds
a rejection, its notes are consumed here — surfaced in warnings on both
paths, inlined into the architect prompt on Path B — and recorded in
the path stage's checkpoint as rejection_feedback.
"""

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from engine.contracts import validate
from engine.kb.manifest import load_manifest
from engine.planning.mapper import map_sections
from engine.planning.obligations import match as match_obligations
from engine.planning.obligations import obligation_ping
from engine.planning.precedent import attach_precedents, scan_prior_plans
from engine.planning.sections import (
    aggregate,
    assert_zero_silent_misses,
    is_answerable,
)
from engine.structure import parse_workbook

ROOT = Path(__file__).resolve().parents[2]
MANIFEST_DEFAULT = ROOT / "config" / "manifests" / "erp-implementation.yaml"
# P16/C7: the reference IS the firm template now (B67§1 — free-form is
# template-driven). Adopters swap their own via this config path (B68§5).
REFERENCE_DEFAULT = ROOT / "config" / "templates" / "firm-default-template.docx"

FROZEN_PLAN = "plan.frozen.json"

# P16: mixed routes into the DESIGNATED machinery (a multi-file target
# set), not a third path value — ~10 downstream consumers branch on
# "A_designated" and mixed identity lives on the brief + the container's
# sources[] (B73 §4). The B37/D28 spec-gap refusal is retired.
_PATH_BY_STRUCTURE = {"designated": "A_designated",
                      "mixed": "A_designated",
                      "free_flow": "B_free_flow"}


@dataclass
class PlanReport:
    pursuit_id: str
    status: str = "complete"  # complete | refused
    path: str | None = None
    warnings: list[str] = field(default_factory=list)
    plan_path: Path | None = None
    slots_path: Path | None = None


def _effort_allocation(frozen: dict) -> str:
    """weighted iff the buyer actually stated evaluation weights; else
    uniform, EXPLICITLY (B33(3), the P10 close of the NOT_YET_WRITTEN
    pin).

    The field was schema-declared with a documented default and no
    writer, which meant every plan claimed the default by omission.
    Writing it makes the choice inspectable — and the condition is the
    honest one: depth should follow weights only where a buyer supplied
    weights to follow. Inventing a weighting from an unweighted matrix
    would be the engine deciding what the buyer cares about."""
    weighted_rows = [row for row in frozen.get("requirements_matrix", [])
                     if row.get("weight") is not None]
    return "weighted" if weighted_rows else "uniform"


def _refuse(log, report: PlanReport, *, stage: str, code: str, message: str
            ) -> PlanReport:
    log.emit("error", stage=stage, error={
        "code": code,
        "message": message,
        "recoverable": True,
        "action_taken": "surfaced_to_human",
    })
    report.status = "refused"
    return report


def run_planning(pursuit, caller, log, store, *, workbook: Path | None = None,
                 targets: list[Path] | None = None,
                 core_doc: Path | None = None,
                 manifest_path: Path = MANIFEST_DEFAULT,
                 reference_path: Path = REFERENCE_DEFAULT) -> PlanReport:
    report = PlanReport(pursuit_id=pursuit.pursuit_id)
    # P16: the target surface is a declared SET; the single `workbook`
    # param folds in as a one-element set for existing callers — but a
    # workbook-derived target is LEGACY-GLOBBED, not declared, so it
    # never triggers the declared-target contradiction below (a stray
    # inbox workbook on a free_flow pursuit was always ignored).
    declared = targets is not None
    if targets is None:
        targets = [Path(workbook)] if workbook is not None else []
    else:
        targets = [Path(t) for t in targets]

    # --- refusal gates: the fork predicate, checked on brief.json -------
    try:
        brief = pursuit.read_artifact("brief.json")
    except FileNotFoundError:
        return _refuse(log, report, stage="pursuit_plan", code="missing_brief",
                       message="no brief.json in the pursuit workspace")
    if brief.get("status") != "approved":
        return _refuse(
            log, report, stage="pursuit_plan", code="brief_not_approved",
            message=f"brief status is {brief.get('status')!r} — planning "
                    "requires a Gate-1-approved brief",
        )
    if not (pursuit.root / "brief.frozen.json").exists():
        return _refuse(
            log, report, stage="pursuit_plan", code="missing_frozen_brief",
            message="brief is approved but brief.frozen.json is missing — "
                    "the Gate-1 freeze is the planning input (T7)",
        )
    if (pursuit.root / FROZEN_PLAN).exists():
        return _refuse(
            log, report, stage="pursuit_plan", code="plan_frozen",
            message="plan.frozen.json exists — an approved plan may not be "
                    "rebuilt (T7 analog); Gate-2 rejection is the redo door",
        )

    frozen = pursuit.read_artifact("brief.frozen.json")  # content authority
    structure = frozen.get("procurement", {}).get("response_structure")
    if not structure:
        return _refuse(
            log, report, stage="pursuit_plan", code="missing_response_structure",
            message="the brief names no response_structure — the fork cannot "
                    "route this pursuit",
        )
    if structure not in _PATH_BY_STRUCTURE:
        return _refuse(
            log, report, stage="pursuit_plan",
            code="unsupported_response_structure",
            message=f"response_structure {structure!r} is outside the "
                    "vocabulary — the fork cannot route this pursuit",
        )
    if structure == "free_flow" and declared and targets:
        # Defense in depth behind the gate_0 warning (P16): a declared
        # target is authoritative evidence AGAINST free_flow — degrading
        # to the firm template would silently drop the buyer's own form.
        return _refuse(
            log, report, stage="pursuit_plan",
            code="declared_target_contradicts_free_flow",
            message=f"{len(targets)} declared target(s) exist but the brief "
                    "says free_flow — correct response_structure at gate_0 "
                    "or withdraw the target role; refusing to drop a "
                    "declared form on the floor",
        )
    report.path = _PATH_BY_STRUCTURE[structure]
    manifest = load_manifest(manifest_path)  # malformed firm config raises

    # --- rejection feedback (redo loop) ---------------------------------
    feedback = None
    if "gate_2" in pursuit.completed_stages():
        gate = pursuit.checkpoint_payload("gate_2")
        if gate.get("decision") == "rejected":
            feedback = gate.get("notes")
            report.warnings.append(
                f"replanning after gate_2 rejection by {gate.get('actor')}: "
                f"{feedback}"
            )

    # --- the fork -------------------------------------------------------
    if report.path == "A_designated":
        stage = "path_a_map"
        if stage not in pursuit.completed_stages():
            refused = _run_path_a(pursuit, log, store, frozen, manifest,
                                  feedback, targets, core_doc, structure,
                                  report)
            if refused is not None:
                return refused
    else:
        stage = "path_b_outline"
        if stage not in pursuit.completed_stages():
            from engine.planning.outline import run_path_b

            refused = run_path_b(pursuit, caller, log, store, frozen, manifest,
                                 feedback, reference_path, report)
            if refused is not None:
                return refused

    # --- pursuit_plan: replay-always assembly from the checkpoint -------
    payload = pursuit.checkpoint_payload(stage)
    report.warnings.extend(
        w for w in payload.get("warnings", []) if w not in report.warnings
    )
    log.emit("stage_start", stage="pursuit_plan")
    plan: dict = {
        "pursuit_id": pursuit.pursuit_id,
        "path": report.path,
        "effort_allocation": _effort_allocation(frozen),
        "sections": payload["sections"],
        "obligations": payload["obligations"],
        "coverage_summary": payload["coverage"],
        "status": "gate2_pending",
    }
    if payload.get("slots_sha256"):  # both paths carry slots now (P16/C7)
        plan["slots_ref"] = "slots.json"
        report.slots_path = pursuit.root / "slots.json"
    plan_path = pursuit.write_artifact("pursuit_plan", plan)
    log.emit("artifact", stage="pursuit_plan", artifact={
        "kind": "pursuit_plan",
        "path": str(plan_path),
        "sha256": hashlib.sha256(plan_path.read_bytes()).hexdigest(),
    })
    pursuit.checkpoint("pursuit_plan", {
        "plan_sha256": hashlib.sha256(plan_path.read_bytes()).hexdigest(),
    })
    log.emit("stage_end", stage="pursuit_plan")
    report.plan_path = plan_path
    return report


def _run_path_a(pursuit, log, store, frozen: dict, manifest, feedback,
                targets: list[Path], core_doc: Path | None, structure: str,
                report: PlanReport) -> PlanReport | None:
    """The guarded Path-A stage. Returns a refused report or None."""
    from engine.structure import StructureError, merge_parsed, parse_target
    from engine.structure.targets import scan_core_document

    missing = [t for t in targets if not t.is_file()]
    if not targets or missing:
        return _refuse(
            log, report, stage="path_a_map", code="missing_structure_doc",
            message=("Path A requires the declared target document(s) and "
                     + (f"these are missing: "
                        f"{', '.join(m.name for m in missing)}"
                        if missing else "none were provided")),
        )

    log.emit("stage_start", stage="path_a_map")
    parsed_list = []
    for target in targets:
        try:
            parsed = parse_target(target)
        except StructureError as exc:
            # P16: a declared target the engine cannot classify FAILS
            # LOUDLY — never a silent degrade to free_flow.
            log.emit("error", stage="path_a_map", error={
                "code": "unclassifiable_target",
                "message": str(exc),
                "recoverable": True,
                "action_taken": "surfaced_to_human",
            })
            log.emit("stage_end", stage="path_a_map")
            report.status = "refused"
            return report
        if not parsed.slots:
            # EC-3's contract: an empty parse of a real document REFUSES
            # loudly — a zero-slot plan is the silent miss this engine
            # exists to prevent. No checkpoint: a fixed parser reruns.
            log.emit("error", stage="path_a_map", error={
                "code": "empty_parse",
                "message": f"{parsed.file}: parsed to zero slots — refusing "
                           "to plan around an empty structure (EC-3)",
                "recoverable": True,
                "action_taken": "surfaced_to_human",
            })
            log.emit("stage_end", stage="path_a_map")
            report.status = "refused"
            return report
        parsed_list.append(parsed)

    if structure == "mixed" and core_doc is not None:
        scanned = scan_core_document(core_doc)
        if scanned is None:
            report.warnings.append(
                f"mixed pursuit: core document {Path(core_doc).name} is not "
                "scannable offline — embedded response structure, if any, "
                "is NOT captured (recorded, not faked; A1/extraction "
                "closes — B67-F4 precedent)")
        elif scanned.slots:
            parsed_list.append(scanned)

    for parsed in parsed_list:
        for slot in parsed.slots:
            validate("target_slot", slot)
    container = {"pursuit_id": pursuit.pursuit_id,
                 **merge_parsed(parsed_list)}
    slots_path = pursuit.write_artifact("target_slots", container,
                                        name="slots.json")
    log.emit("artifact", stage="path_a_map", artifact={
        "kind": "target_slots",
        "path": str(slots_path),
        "sha256": hashlib.sha256(slots_path.read_bytes()).hexdigest(),
    })

    slots_by_id = {s["slot_id"]: s for s in container["slots"]}
    sections = aggregate(container["slots"])

    # requirement_refs: brief matrix refs matched by slot ref_ids.
    matrix_refs = {
        row["ref"] for row in frozen.get("requirements_matrix", [])
        if row.get("ref")
    }
    for section in sections:
        refs = sorted({
            slots_by_id[sid].get("ref_id")
            for sid in section["slot_ids"]
            if slots_by_id[sid].get("ref_id") in matrix_refs
        })
        if refs:
            section["requirement_refs"] = refs

    # Win themes (pinned Path-A rule, B28): every approved theme on every
    # narrative section; the P7 drafter decides usage.
    approved = frozen.get("win_themes", {}).get("approved", [])
    for section in sections:
        if approved and any(
            is_answerable(slots_by_id[sid]) for sid in section["slot_ids"]
        ):
            section["win_themes"] = list(approved)

    dispositions = map_sections(store, sections, slots_by_id,
                                log=log, stage="path_a_map")
    assert_zero_silent_misses(container["slots"], sections, dispositions)

    texts_by_section = {
        s["section_id"]: [
            slots_by_id[sid]["question_text"]
            for sid in s["slot_ids"]
            if slots_by_id[sid].get("question_text")
        ]
        for s in sections
    }
    obligations = match_obligations(manifest, sections, texts_by_section)

    _number_and_emit_gaps(pursuit, log, "path_a_map", sections, obligations,
                          slots_by_id=slots_by_id)

    priors, skipped = scan_prior_plans(pursuit.root.parent,
                                       self_id=pursuit.pursuit_id)
    report.warnings.extend(skipped)
    attach_precedents(sections, priors, texts_by_section=texts_by_section)

    total = sum(1 for d in dispositions.values() if d in ("grounded", "gapped"))
    open_gaps = sum(len(s.get("gaps", [])) for s in sections)
    payload = {
        "slots_sha256": hashlib.sha256(slots_path.read_bytes()).hexdigest(),
        "slot_count": container["slot_count"],
        "source_sha256": container["source_sha256"],
        "sections": sections,
        "obligations": obligations,
        "coverage": {
            "total_requirements": total,
            "covered": total - open_gaps,
            "open_gaps": open_gaps,
            "omit_approved": 0,
            "draft_flagged": 0,
        },
        "warnings": report.warnings,
    }
    if feedback:
        payload["rejection_feedback"] = feedback
    pursuit.checkpoint("path_a_map", payload)
    log.emit("stage_end", stage="path_a_map")
    return None


def _number_and_emit_gaps(pursuit, log, stage: str, sections: list[dict],
                          obligations: list[dict], *,
                          slots_by_id: dict | None = None) -> None:
    """Assign gap_ids in deterministic order (section order -> gap order,
    then gapped obligations in manifest order) and emit one run-log gap
    line per gap. Runs ONLY in the guarded stage — replays must not
    re-count totals.gaps_opened."""
    counter = 0
    for section in sections:
        for gap in section.get("gaps", []):
            counter += 1
            gap["gap_id"] = f"gap_{pursuit.pursuit_id}_plan_{counter:02d}"
            target = {"section_id": section["section_id"]}
            slot_id = gap.get("slot_id")
            if slot_id:
                slot = (slots_by_id or {}).get(slot_id, {})
                target["slot_ref_id"] = slot.get("ref_id") or slot_id
            log.emit("gap", stage=stage, gap={
                "gap_id": gap["gap_id"],
                "reason": "kb_empty",  # no_content and thin_content both
                "question_to_human": gap["question_to_human"],
                "resolution": "unresolved",
            }, target=target)
    for obligation in obligations:
        if obligation["status"] != "gapped":
            continue
        counter += 1
        log.emit("gap", stage=stage, gap={
            "gap_id": f"gap_{pursuit.pursuit_id}_plan_{counter:02d}",
            "reason": "needs_sme",
            "question_to_human": obligation_ping(obligation),
            "resolution": "unresolved",
        })
