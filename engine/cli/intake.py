"""intake command group (P3): run the bid-brief stage over a document
package, offline. `--wire` supplies the canned intake_analyst JSON — the
pre-production is zero-spend (FakeCaller only); the live caller arrives at P8
behind RFP_LIVE.

This is the production construction site for the extraction backend (C9,
B57): pdf/docx packages resolve docling here, and an unavailable backend
REFUSES the run rather than quietly downgrading (the owner's call, B58) —
RFP_EXTRACTION_FALLBACK=1 is the explicit override, degraded-stamped."""

import json
import os
from pathlib import Path


def _cmd_run(args) -> int:
    from engine.extraction.backend import (
        FALLBACK_ENV,
        ExtractionUnavailable,
        resolve_backend,
    )
    from engine.intake.brief import IntakeDoc, IntakePackage, run_intake
    from engine.llm import FakeCaller, TracedCaller, effective_config
    from engine.runlog import RunLogger
    from engine.version import engine_version
    from engine.workspace import PursuitDir

    docs = []
    for spec in args.doc:
        path, _, kind = spec.rpartition(":")
        if not path:
            print(f"--doc expects PATH:KIND, got {spec!r}")
            return 1
        docs.append(IntakeDoc(path=Path(path), kind=kind))
    package = IntakePackage(pursuit_id=args.pursuit, docs=docs, ramble=args.ramble)

    pursuit = PursuitDir(Path(args.outputs), args.pursuit)
    log = RunLogger(pursuit.root, pursuit.new_run_id(), args.pursuit)
    wire_text = Path(args.wire).read_text(encoding="utf-8")
    caller = TracedCaller(FakeCaller({"intake_analyst": wire_text}), log)
    log.run_start(mode="dry_run", engine_version=engine_version(),
                  config=effective_config(), kb_snapshot="kb@empty")

    extraction = None
    needs_backend = any(
        Path(d.path).suffix.lower() in (".pdf", ".docx") for d in docs
    )
    if needs_backend and not os.environ.get(FALLBACK_ENV):
        try:
            extraction = resolve_backend()
        except ExtractionUnavailable as exc:
            log.emit("error", stage="intake", error={
                "code": "extraction_backend_unavailable",
                "message": str(exc),
                "recoverable": True,
                "action_taken": "surfaced_to_human",
            })
            log.run_end(status="failed")
            print("status: refused")
            print(f"error: {exc}")
            return 1

    report = run_intake(pursuit, caller, log, package, extraction=extraction)
    log.run_end(status="completed" if report.status != "refused" else "failed")

    print(f"status: {report.status}")
    if report.brief_path:
        print(f"brief: {report.brief_path}")
        brief = json.loads(report.brief_path.read_text(encoding="utf-8"))
        print(f"matrix rows: {len(brief['requirements_matrix'])}  "
              f"red flags: {len(brief['procurement'].get('red_flags', []))}")
    for miss in report.misses:
        print(f"gap [{miss['target']}]: {miss['question']}")
    for warning in report.warnings:
        print(f"warning: {warning}")
    return 1 if report.status == "refused" else 0


def register(sub) -> None:
    intake = sub.add_parser("intake", help="Intake & bid brief (P3)")
    isub = intake.add_subparsers(dest="intake_command", required=True)

    run = isub.add_parser("run", help="document package + ramble -> brief.json")
    run.add_argument("--outputs", required=True, help="pursuits root directory")
    run.add_argument("--pursuit", required=True, help="pursuit id")
    run.add_argument("--doc", action="append", required=True, metavar="PATH:KIND",
                     help="repeatable; KIND per intake.documents (e.g. rfp_main)")
    run.add_argument("--ramble", default=None, help="pursuit-lead context, verbatim")
    run.add_argument("--wire", required=True,
                     help="file holding the canned intake_analyst JSON (offline)")
    run.set_defaults(fn=_cmd_run)
