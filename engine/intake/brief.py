"""Bid-brief stage (P3/WP2): buyer package + pursuit-lead ramble → brief.json.

Model proposes, code writes (the P2 ingest shape): one starved call returns
a narrow wire model; code owns document extraction, the injection-flag
union, weight and deadline parsing, the completeness predicate, and every
write. Stage boundary (B19): `intake` = deterministic work (extraction,
screen, checkpoints), `bid_brief` = the model call + artifact write.

The brief's `created` field is deliberately not written at P3: the artifact
must be byte-identical across a kill/resume (N2), and a wall-clock stamp
would break that for no consumer — Gate 1 (P5) stamps its own datetime.

Completeness (recorded 2026-07-31 — TODO(spec-gap): v2-local target list,
calibrated at P10's eval harness and re-checked against the A3 bench, B30(c)):
buyer.name, what_is_bought, response_structure, matrix ≥ 1 row, deadlines
whenever the date scan found candidates, and at least as many weighted
matrix rows as distinct stated-weight values seen in the documents. Every
miss emits a run-log gap record — filled, or gapped with a reason, never
silent. The brief still writes as status="draft".
"""

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from engine.contracts import ContractError
from engine.extraction.backend import ExtractionFailed
from engine.extraction.twopath import two_path_review
from engine.intake.extract import (
    ExtractedDoc,
    UnreadableRfp,
    extract,
    location_of,
    parse_date,
)
from engine.intake.screen import screen
from engine.llm.frames import wrap_lead_context, wrap_untrusted

ROOT = Path(__file__).resolve().parents[2]
_PROMPT_PATH = ROOT / "prompts" / "intake_analyst" / "prompt.md"
_QUESTIONER_PROMPT = ROOT / "prompts" / "intake_questioner" / "prompt.md"

# The questioner's brevity contract (P15/B67 §4), enforced in CODE —
# "clean, crisp questions": one ask, one sentence, one "?", length-capped.
# Violations are dropped-and-reported, never rendered.
QUESTION_CHAR_CAP = 200

FLAG_KINDS = [
    "injection", "ai_use", "independence_oci", "onerous_term",
    "unrealistic_timeline", "wired_for_incumbent", "hidden_content", "other",
]
RESPONSE_STRUCTURES = ["designated", "free_flow", "mixed"]
# TODO(spec-gap): routed_to is a constant until real identities exist to
# name a conflicts owner — closer A5 (the SSO/header-auth lift), trigger:
# the first directory-backed login. Originally deferred to "the P9 auth
# seam"; P9 closed 2026-08-10 having built the seam without named owners,
# and the carrier survived pointing at a closed phase until the pre-P12
# audit re-pointed it (B49/F-1). (C3: flag and hand off, never adjudicate.)
OCI_ROUTE = "conflicts_process"


@dataclass
class IntakeDoc:
    path: Path
    kind: str  # intake.documents kind enum value
    # P15/B67 §3: declared document role (core|supplemental|target) —
    # never inferred from the upload; None means undeclared (legacy path)
    role: str | None = None


@dataclass
class IntakePackage:
    pursuit_id: str
    docs: list[IntakeDoc]
    ramble: str | None = None


@dataclass
class IntakeReport:
    pursuit_id: str
    status: str = "complete"  # complete | incomplete | refused
    warnings: list[str] = field(default_factory=list)
    misses: list[dict] = field(default_factory=list)
    red_flags: list[dict] = field(default_factory=list)
    brief_path: Path | None = None


# --------------------------------------------------------------- wire parse

_WIRE_BUYER_KEYS = {"name", "vertical", "profile", "terminology", "incumbent"}
_WIRE_PROC_KEYS = {
    "what_is_bought", "response_structure", "submission_method",
    "required_forms", "deadlines",
}
_WIRE_REQ_KEYS = {"ref", "requirement", "section", "weight_text", "mandatory"}
_WIRE_FLAG_KEYS = {"kind", "detail", "excerpt", "source_location"}


def parse_wire(text: str) -> tuple[dict, list[str]]:
    """Whitelist the model's proposal. Out-of-vocab values are CLEARED and
    reported, never silently dropped (v1 defect 1); unknown keys are dropped
    and reported."""
    try:
        raw = json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ContractError(f"intake_analyst returned unparseable JSON: {exc}") from exc
    cleared: list[str] = []

    def take(obj: dict, allowed: set[str], label: str) -> dict:
        kept = {k: v for k, v in obj.items() if k in allowed and v not in (None, "", [])}
        for k in sorted(set(obj) - allowed):
            cleared.append(f"{label}.{k}: unknown key dropped")
        return kept

    wire = {
        "buyer": take(raw.get("buyer") or {}, _WIRE_BUYER_KEYS, "buyer"),
        "procurement": take(raw.get("procurement") or {}, _WIRE_PROC_KEYS, "procurement"),
        "requirements": [
            take(r, _WIRE_REQ_KEYS, f"requirements[{i}]")
            for i, r in enumerate(raw.get("requirements") or [])
            if isinstance(r, dict) and r.get("requirement")
        ],
        "red_flags": [],
    }
    structure = wire["procurement"].get("response_structure")
    if structure is not None and structure not in RESPONSE_STRUCTURES:
        cleared.append(f"procurement.response_structure: out-of-vocab {structure!r} cleared")
        del wire["procurement"]["response_structure"]
    for i, flag in enumerate(raw.get("red_flags") or []):
        if not isinstance(flag, dict) or not flag.get("detail"):
            cleared.append(f"red_flags[{i}]: malformed entry dropped")
            continue
        kept = take(flag, _WIRE_FLAG_KEYS, f"red_flags[{i}]")
        if kept.get("kind") not in FLAG_KINDS:
            cleared.append(f"red_flags[{i}].kind: out-of-vocab {kept.get('kind')!r} -> other")
            kept["kind"] = "other"
        wire["red_flags"].append(kept)
    return wire, cleared


_WEIGHT_PERCENT = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*%")
_WEIGHT_POINTS = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*(?:points?|pts)\b", re.I)


def parse_weight(text: str) -> tuple[float | None, str | None]:
    """'Technical capability (30%)' -> (30, 'percent'). Verbatim-as-stated
    (B17): the number is never normalized."""
    match = _WEIGHT_PERCENT.search(text)
    if match:
        return float(match.group(1)), "percent"
    match = _WEIGHT_POINTS.search(text)
    if match:
        return float(match.group(1)), "points"
    return None, None


# ------------------------------------------------------------- flag union


def _merge_flags(model_flags: list[dict], screen_flags, docs: list[ExtractedDoc]) -> list[dict]:
    """Screen ∪ model, either-alone-fires. A model injection flag matching a
    screen flag's excerpt collapses into one flag with detected_by='both'."""
    merged: list[dict] = []
    for flag in model_flags:
        out = dict(flag, detected_by="model")
        if out["kind"] == "independence_oci":
            out["routed_to"] = OCI_ROUTE
        merged.append(out)

    def _matches(model_flag: dict, excerpt: str) -> bool:
        probe = (model_flag.get("excerpt") or model_flag["detail"])[:40]
        return bool(probe) and (probe in excerpt or excerpt[:40] in probe)

    for sf in screen_flags:
        twin = next(
            (f for f in merged if f["kind"] == "injection" and _matches(f, sf.excerpt)),
            None,
        )
        if twin is not None:
            twin["detected_by"] = "both"
            twin.setdefault("source_location", sf.source_location)
            continue
        merged.append({
            "kind": "injection",
            "detail": f"deterministic screen: {sf.pattern_id}",
            "excerpt": sf.excerpt,
            "source_location": sf.source_location,
            "detected_by": "screen",
        })
    for doc in docs:
        for seg in doc.hidden_segments:
            merged.append({
                "kind": "hidden_content",
                "detail": "content hidden in the buyer file (hidden sheet, row or column)",
                "excerpt": seg["text"][:200],
                "source_location": seg["location"],
                "detected_by": "screen",
            })
    return merged


# ------------------------------------------------------------ completeness

_WEIGHT_CANDIDATE = re.compile(
    r"\(\d{1,3}(?:\.\d+)?%\)"                # (30%)
    r"|:\s*\d{1,3}(?:\.\d+)?%"               # : 40%
    r"|\|\s*\d{1,3}(?:\.\d+)?%\s*(?=\|)"     # | 45% |  a cell holding only the percent
    r"|^[ \t]*\d{1,3}(?:\.\d+)?%[ \t]*$",    # 45% alone on its line (pdf table column)
    re.MULTILINE)


def _stated_weight_values(docs: list[ExtractedDoc]) -> list[str]:
    """Criterion-shaped weight statements, ONE ENTRY PER OCCURRENCE.

    Two shapes match beyond the prose forms '(30%)' / ': 40%' — the
    bare table cell (pipe-bounded, how the extractors render xlsx/docx
    tables) and the percent-alone line (how a pdf table column falls
    out). Prose percents ('95% uptime') still deliberately do not match:
    every alternative requires the percent to stand alone in its cell,
    line, parens, or after a colon. Returns a LIST, not a set — two
    criteria both weighted 20% are two stated weights (B67-F1: the set
    dedup plus the bare-cell blindness let a brief report complete on
    weights it never found)."""
    values: list[str] = []
    for doc in docs:
        for match in _WEIGHT_CANDIDATE.finditer(doc.text):
            values.append(
                re.search(r"\d{1,3}(?:\.\d+)?%", match.group(0)).group(0))
    return values


def _brevity_violation(question: str) -> str | None:
    """The testable half of 'clean, crisp questions' (B67 §4). Returns
    the reason a question is dropped, or None when it passes."""
    q = question.strip()
    if not q:
        return "empty"
    if len(q) > QUESTION_CHAR_CAP:
        return f"over {QUESTION_CHAR_CAP} chars"
    if q.count("?") != 1 or not q.endswith("?"):
        return "must be a single question ending in one '?'"
    if ". " in q or "; " in q:
        return "one sentence per question"
    return None


def run_questioner(caller, log, brief: dict, parts: list[str],
                   warnings: list[str], *, pursuit_id: str) -> None:
    """The advisory questioner (P15/B67 §4): one mid-tier call whose
    questions land beside the completeness gaps marked origin=questioner
    — skippable, uncapped in COUNT, brevity-capped in FORM, and consumed
    by NO gate (E5/A4: an uncalibrated asker gates nothing; a question
    block that blocks trains review fatigue). Absent-safe: an
    unparseable wire records 'unavailable' and appends nothing — the
    red-team lane's recorded-not-faked rule."""
    existing = brief.get("intake", {}).get("gaps", [])
    asked = "\n".join(f"- {g['question_to_human']}" for g in existing)
    prompt = "\n\n".join(parts + (
        [f"ALREADY ASKED (do not repeat):\n{asked}"] if asked else []))
    result = caller.call(
        "intake_questioner", tier="mid", prompt=prompt,
        system=_QUESTIONER_PROMPT.read_text(encoding="utf-8"),
        stage="bid_brief")
    try:
        raw = json.loads(result.text)
        questions = raw["questions"]
        assert isinstance(questions, list)
    except (json.JSONDecodeError, TypeError, KeyError, AssertionError):
        warnings.append(
            "advisory questions unavailable this run (recorded, not faked)")
        return
    gaps = brief.setdefault("intake", {}).setdefault("gaps", [])
    n = len(gaps)
    for item in questions:
        question = str((item or {}).get("question", "")) if isinstance(
            item, dict) else ""
        why = _brevity_violation(question)
        if why is not None:
            warnings.append(
                f"questioner question dropped ({why}): {question[:60]!r}")
            continue
        n += 1
        gap = {"gap_id": f"gap_{pursuit_id}_intake_{n:02d}",
               "reason": "needs_sme",
               "question_to_human": question.strip(),
               "origin": "questioner", "status": "open"}
        target = (item.get("target") or "").strip()
        if target:
            gap["target"] = target
        gaps.append(gap)
        log.emit("gap", stage="bid_brief", gap={
            "gap_id": gap["gap_id"], "reason": "needs_sme",
            "question_to_human": gap["question_to_human"],
            "resolution": "unresolved",
        })
    if not gaps:
        # nothing from either source — writers-omit holds
        brief["intake"].pop("gaps", None)


def _assumption_register(brief: dict) -> list[dict]:
    """The assumption register (P15/B70): every STRUCTURED inference the
    model made, listed for gate_0 confirmation — a confident-but-wrong
    inference is worse than a gap, because a gap announces itself and a
    wrong `what_is_bought` poisons every downstream stage silently.

    Granularity is deliberate: scalar routing fields plus the two
    per-item hybrids (deadline text/date, weight text/number). Prose
    fields (buyer.profile, requirement text) are excluded — they render
    verbatim on the gate_0 screen already, and a register that lists
    everything teaches its reader to confirm nothing. Code-parsed values
    ride along as source="code": shown for context, not confirmable —
    correcting one means correcting the model text it was parsed from.
    Absent fields get no entry (the writers-omit rule)."""
    entries: list[dict] = []

    def add(field: str, value, source: str) -> None:
        if value not in (None, "", []):
            entries.append({"field": field, "value": value,
                            "source": source, "status": "unconfirmed"})

    add("buyer.name", brief["buyer"].get("name"), "model")
    add("buyer.vertical", brief["buyer"].get("vertical"), "model")
    add("buyer.incumbent", brief["buyer"].get("incumbent"), "model")
    proc = brief["procurement"]
    add("procurement.what_is_bought", proc.get("what_is_bought"), "model")
    add("procurement.response_structure", proc.get("response_structure"), "model")
    add("procurement.submission_method", proc.get("submission_method"), "model")
    for i, deadline in enumerate(proc.get("deadlines", [])):
        add(f"procurement.deadlines[{i}].date_text",
            deadline.get("date_text"), "model")
        add(f"procurement.deadlines[{i}].date", deadline.get("date"), "code")
    for i, row in enumerate(brief["requirements_matrix"]):
        add(f"requirements_matrix[{i}].weight_text",
            row.get("weight_text"), "model")
        if "weight" in row:
            add(f"requirements_matrix[{i}].weight", row["weight"], "code")
    return entries


def completeness(brief: dict, docs: list[ExtractedDoc]) -> list[dict]:
    misses: list[dict] = []

    def miss(target: str, reason: str, question: str) -> None:
        misses.append({"target": target, "reason": reason, "question": question})

    if not brief["buyer"].get("name"):
        miss("buyer.name", "needs_sme", "Buyer name not found in the package — who is soliciting?")
    if not brief["procurement"].get("what_is_bought"):
        miss("procurement.what_is_bought", "needs_sme",
             "Could not determine what is being procured.")
    if not brief["procurement"].get("response_structure"):
        miss("procurement.response_structure", "needs_sme",
             "Response structure (designated/free_flow/mixed) not determinable.")
    if not brief["requirements_matrix"]:
        miss("requirements_matrix", "needs_sme", "No requirements extracted from the package.")
    if any(doc.date_candidates for doc in docs) and not brief["procurement"].get("deadlines"):
        miss("procurement.deadlines", "needs_sme",
             "Date-like text found in the documents but no deadlines extracted.")
    stated = _stated_weight_values(docs)
    weighted_rows = [r for r in brief["requirements_matrix"] if "weight" in r]
    if len(weighted_rows) < len(stated):
        miss("requirements_matrix.weight", "ambiguous_requirement",
             f"Documents state weights {sorted(stated)} but only "
             f"{len(weighted_rows)} matrix rows carry one.")
    return misses


# ------------------------------------------------------------------ stage


def run_intake(pursuit, caller, log, package: IntakePackage, *,
               extraction=None) -> IntakeReport:
    """`extraction` is the docling backend for pdf/docx (B57 adoption);
    None means the legacy stacks read them, stamped degraded (the
    construction site owns resolution + the loud refusal — B58)."""
    report = IntakeReport(pursuit_id=package.pursuit_id)

    # Refusal gate: every document must be readable before any spend.
    try:
        docs = [extract(d.path, backend=extraction) for d in package.docs]
    except UnreadableRfp as exc:
        log.emit("error", stage="intake", error={
            "code": "unreadable_rfp",
            "message": str(exc),
            "recoverable": True,
            "action_taken": "surfaced_to_human",
        })
        report.status = "refused"
        return report
    for doc in docs:
        report.warnings.extend(f"{doc.file}: {w}" for w in doc.warnings)
    screen_flags = {doc.file: screen(doc) for doc in docs}

    done = pursuit.completed_stages()
    if "intake" not in done:
        log.emit("stage_start", stage="intake")
        for doc in docs:
            log.emit("validation", stage="intake", validation={
                "check": "injection_screen",
                "result": "flag" if screen_flags[doc.file] else "pass",
            })
        # C10 two-path tripwire (§A2.3, production half): PDFs whose
        # docling read produced tables get a second, VLM-mode read and a
        # cell diff — the proven fabrication surface (DOCX parses XML on
        # both paths; its diff is consistency-only, skipped). No answer
        # key exists in production, so ANY divergence — or a VLM leg that
        # cannot run — forces review; nothing is scored, and the VLM view
        # is discarded (it never enters an artifact). Inside the
        # checkpoint guard: resume never re-spends the second read.
        two_path: dict = {}
        if extraction is not None:
            for d, doc in zip(package.docs, docs):
                if (doc.format == "pdf" and doc.extractor == "docling"
                        and doc.grids):
                    try:
                        vlm = extraction.convert(Path(d.path), mode="vlm")
                        review = two_path_review(
                            doc.grids,
                            [{"grid": t.grid, "merges": t.merges}
                             for t in vlm.grids],
                        )
                    except ExtractionFailed as exc:
                        review = {"tables_diffed": 0, "findings": [],
                                  "error": f"vlm path failed: {str(exc)[:200]}"}
                    if review["findings"]:
                        doc.extraction_flags.append("two_path_divergence")
                    elif review.get("error"):
                        doc.extraction_flags.append("two_path_unavailable")
                    two_path[doc.file] = review

        # C10: degraded extraction still ingests, flagged — one record per
        # document, plus the workspace extraction artifact (resume-stable:
        # inside the checkpoint guard, no timing). mandatory_review is
        # code-forced from the flags (the planning-gate idiom): no payload
        # shape can unset it.
        for doc in docs:
            log.emit("validation", stage="intake", validation={
                "check": "extraction",
                "result": "flag"
                if (doc.extraction_degraded or doc.extraction_flags)
                else "pass",
            })
        pursuit.write_json("extraction.json", {
            "docs": [
                {
                    "file": doc.file,
                    "extractor": doc.extractor,
                    "extraction_fingerprint": doc.extraction_fingerprint,
                    "degraded": doc.extraction_degraded,
                    "flags": doc.extraction_flags,
                    "mandatory_review": bool(
                        doc.extraction_degraded or doc.extraction_flags
                    ),
                }
                for doc in docs
            ],
            "two_path": two_path,
        })
        pursuit.checkpoint("intake", {
            "docs": [
                {
                    "file": doc.file,
                    "kind": d.kind,
                    "format": doc.format,
                    "sha256": hashlib.sha256(Path(d.path).read_bytes()).hexdigest(),
                    # C9: which stack read it, resume-stable (no timing).
                    "extractor": doc.extractor,
                    "extraction_fingerprint": doc.extraction_fingerprint,
                    "extraction_degraded": doc.extraction_degraded,
                    "extraction_flags": doc.extraction_flags,
                }
                for d, doc in zip(package.docs, docs)
            ],
            "warnings": report.warnings,
            "screen_flags": [
                {"file": f, "pattern_id": sf.pattern_id, "excerpt": sf.excerpt}
                for f, flags in screen_flags.items() for sf in flags
            ],
            "date_candidates": [c for doc in docs for c in doc.date_candidates],
        })
        log.emit("stage_end", stage="intake")

    log.emit("stage_start", stage="bid_brief")

    # One starved call: framed documents + lead context + vocabulary, never
    # a motive. All buyer text enters through wrap_untrusted — no exceptions.
    system = _PROMPT_PATH.read_text(encoding="utf-8")
    parts = [wrap_untrusted(doc.file, doc.text) for doc in docs]
    if package.ramble:
        parts.append(wrap_lead_context(package.ramble))
    parts.append(
        f"Allowed red_flag kinds: {', '.join(FLAG_KINDS)}\n"
        f"Allowed response_structure values: {', '.join(RESPONSE_STRUCTURES)}"
    )
    result = caller.call("intake_analyst", tier="frontier",
                         prompt="\n\n".join(parts), system=system, stage="bid_brief")
    wire, cleared = parse_wire(result.text)
    report.warnings.extend(cleared)

    # Code assembles the brief. The model proposed; code owns every field.
    matrix = []
    for row in wire["requirements"]:
        entry = {k: row[k] for k in ("ref", "requirement", "section", "mandatory") if k in row}
        weight_text = row.get("weight_text")
        if weight_text:
            # P15/C5a: the buyer's statement is retained verbatim (B17
            # evidence) — it is the register's correction target, and the
            # parse follows the text, never the other way around
            entry["weight_text"] = weight_text
            weight, basis = parse_weight(weight_text)
            if weight is None:
                report.warnings.append(f"weight text not parseable: {weight_text!r}")
            else:
                entry["weight"] = weight
                entry["weight_basis"] = basis
        matrix.append(entry)
    percent_rows = [r["weight"] for r in matrix if r.get("weight_basis") == "percent"]
    if percent_rows and sum(percent_rows) != 100:
        report.warnings.append(
            f"stated percent weights sum to {sum(percent_rows):g}, not 100"
        )

    deadlines = []
    for item in wire["procurement"].pop("deadlines", []):
        date_text = item.get("date_text", "")
        entry = {"label": item.get("label", ""), "date_text": date_text}
        parsed = parse_date(date_text)
        if parsed:
            entry["date"] = parsed
        elif date_text:
            report.warnings.append(f"deadline date not parseable: {date_text!r}")
        for doc in docs:
            pos = doc.text.find(date_text) if date_text else -1
            if pos >= 0:
                entry["source_location"] = location_of(doc.text, pos, doc.file)
                break
        deadlines.append(entry)

    report.red_flags = _merge_flags(
        wire["red_flags"], [sf for flags in screen_flags.values() for sf in flags], docs
    )

    brief = {
        "pursuit_id": package.pursuit_id,
        "intake": {
            "documents": [
                {"file": doc.file, "kind": d.kind, "format": doc.format,
                 **({"role": d.role} if d.role else {})}
                for d, doc in zip(package.docs, docs)
            ],
        },
        "buyer": {"name": wire["buyer"].get("name", ""), **{
            k: v for k, v in wire["buyer"].items() if k != "name"
        }},
        "procurement": {
            **wire["procurement"],
            **({"deadlines": deadlines} if deadlines else {}),
            "red_flags": report.red_flags,
        },
        "requirements_matrix": matrix,
        "status": "draft",
    }
    if package.ramble:
        # verbatim, copied by code — the model never touches this field
        brief["intake"]["ramble_context"] = package.ramble

    register = _assumption_register(brief)
    if register:
        brief["intake"]["assumptions"] = register

    report.misses = completeness(brief, docs)
    gaps = []
    for i, miss in enumerate(report.misses, start=1):
        question = f"[{miss['target']}] {miss['question']}"
        gap_id = f"gap_{package.pursuit_id}_intake_{i:02d}"
        # P15/B70: the gap lands on the BRIEF as well as the log — a
        # run-log line alone could never be answered (the ping lane joins
        # artifacts, not logs), which is how every intake question died
        # unresolved for eleven phases.
        gaps.append({"gap_id": gap_id, "target": miss["target"],
                     "reason": miss["reason"], "question_to_human": question,
                     "origin": "completeness", "status": "open"})
        log.emit("gap", stage="bid_brief", gap={
            "gap_id": gap_id,
            "reason": miss["reason"],
            "question_to_human": question,
            "resolution": "unresolved",
        })
    if gaps:
        brief["intake"]["gaps"] = gaps
    if report.misses:
        report.status = "incomplete"

    # the advisory questioner (P15/C8): appends origin=questioner gaps
    # beside the completeness ones; consumed by no gate, absent-safe
    run_questioner(caller, log, brief, parts, report.warnings,
                   pursuit_id=package.pursuit_id)

    path = pursuit.write_artifact("bid_brief", brief)
    report.brief_path = path
    log.emit("artifact", stage="bid_brief", artifact={
        "kind": "bid_brief",
        "path": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    })
    # model-only injection findings get their own screen records — the
    # metric counts flags regardless of which detector saw them
    for flag in report.red_flags:
        if flag["kind"] == "injection" and flag["detected_by"] == "model":
            log.emit("validation", stage="bid_brief", agent="intake_analyst",
                     validation={"check": "injection_screen", "result": "flag"})
    pursuit.checkpoint("bid_brief", {"brief_sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    log.emit("stage_end", stage="bid_brief")
    return report
