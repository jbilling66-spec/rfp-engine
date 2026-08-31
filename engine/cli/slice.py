"""The M1 slice runner (B34(24)) — `make slice` invokes THIS, so the CLI
surface ships with its own liveness proof and the annotated draft cannot
be orphaned while the acceptance command passes.

Stage order lives in engine/pipeline/driver.py since P9/D26 — the ONE
authority the web advance job shares, so the two can never drift. This
file keeps what makes the slice THE SLICE: the committed demo package,
the approved J1 gate policy (every open gap -> draft_flagged), the
digest extras, the liveness verification, and the CLI surface.

CI flavor: FakeCaller over the product-side derive-from-prompt script,
mode="dry_run", zero spend. Live flavor: .env loaded HERE (the one
sanctioned boundary, B34(22)), LiveCaller construction refusals surface
named, mode="live" — the first live-mode record the engine ever writes.
Handoff flavor (P20/B81): the operator seam — judgment travels through
pending-calls/ request/response files, mode="handoff", zero spend.
"""

import hashlib
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from engine.cli.slice_script import ci_script
from engine.drafting.compose import VOICE_DEFAULT
from engine.intake.brief import IntakeDoc, IntakePackage
from engine.kb import KBStore
from engine.llm import (
    FakeCaller,
    HandoffCaller,
    LiveCaller,
    SpendBudget,
    TracedCaller,
    load_env_file,
    model_prices,
)
from engine.pipeline import advance
from engine.runlog import assert_seq_gapless, read_run
from engine.validation import consume_annotated
from engine.validation.validate import ANCHORS_DEFAULT
from engine.workspace import PursuitDir

ROOT = Path(__file__).resolve().parents[2]
DEMO_DIR = ROOT / "tests" / "fixtures"  # committed demo package (data, not code)
DEMO_WORKBOOK = DEMO_DIR / "demo-twin.xlsx"
DEMO_RAMBLE = DEMO_DIR / "demo" / "ramble.md"
DEMO_PACK = DEMO_DIR / "demo" / "research-pack.md"
KB_ROOT = ROOT / "kb"

DEFAULT_AT = "2026-08-08T12:00:00"
ACTOR = "slice_runner"
FLAG_NOTE = "Best effort; flag novel claims."  # the approved J1 policy


@dataclass
class SliceResult:
    status: str = "ok"  # ok | failed | refused
    problems: list[str] = field(default_factory=list)
    ran_stages: list[str] = field(default_factory=list)
    packaging: dict | None = None
    cost_usd: float = 0.0


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _extras(stage: str, kb_root: Path = KB_ROOT) -> dict:
    """Digest-visible run variables per stage (the fixture helpers'
    product-side twins — B16/B27/B31(13)/B34(27)). kb_root parameterized
    since c12: a web workspace may carry its own store, and the fact-
    sheet digest must describe the store the run actually used."""
    extras: dict = {}
    if stage in ("planning", "drafting", "validation"):
        extras["planning"] = {
            "manifest_sha256": _sha(
                ROOT / "config" / "manifests" / "erp-implementation.yaml"),
            "reference_sha256": _sha(
                ROOT / "config" / "templates" / "firm-default-template.docx"),
        }
    if stage in ("drafting", "validation"):
        extras["drafting"] = {"voice_spec_sha256": _sha(VOICE_DEFAULT)}
    if stage == "validation":
        from engine.validation.claims import fact_catalog
        facts = fact_catalog(KBStore(kb_root))
        extras["validation"] = {
            "fact_sheet_sha256": hashlib.sha256(json.dumps(
                [(c["kb_id"], c["summary"], c["verified_date"],
                  c.get("review_due")) for c in facts],
                sort_keys=True).encode("utf-8")).hexdigest(),
            "red_team_rubric": "rt_v1",
            "anchors_sha256": _sha(ANCHORS_DEFAULT),
        }
    return extras


def _canned_dispositions(pursuit) -> list[dict]:
    """The approved J1 policy: every open gap -> draft_flagged; nothing
    omitted, nothing auto-answered — maximizes reviewable drafting."""
    plan = pursuit.read_artifact("plan.json")
    return [
        {"section_id": section["section_id"], "gap_id": gap["gap_id"],
         "action": "draft_flagged", "note": FLAG_NOTE}
        for section in plan.get("sections", [])
        for gap in section.get("gaps", [])
        if gap.get("status") in ("open", "pinged")
    ]


def run_slice(workspace: Path, *, live: bool = False, handoff: bool = False,
              handoff_timeout: float = 900.0, at: str = DEFAULT_AT,
              script: dict | None = None, out=print) -> SliceResult:
    result = SliceResult()
    if live:
        load_env_file(ROOT / ".env")  # the one sanctioned .env read (B34(22))
        try:
            live_caller = LiveCaller()  # refusals are named, spend nothing
        except Exception as exc:
            result.status = "refused"
            result.problems.append(str(exc))
            out(f"slice --live refused: {exc}")
            return result
        prices = model_prices()["prices"]
        # ONE budget shared by every stage's caller: the per-run ceiling
        # bounds a single run, but a walk opens a run per stage, so
        # without this the worst case scaled with stage count (recorded decision,
        # 2026-08-10). Far above anything observed — P8's whole live
        # milestone was $5.66 — because this is a runaway guard, not a
        # budget.
        budget = SpendBudget()

        def make_caller(log):
            return TracedCaller(live_caller, log, prices=prices,
                                budget=budget)
        mode = "live"
    elif handoff:
        # P20/B81: the operator seam — judgment travels through
        # pending-calls/ request/response files, no API, no marginal
        # dollar (cost_usd prices handoff/ models at zero). No budget
        # wiring: there is nothing to spend.
        base = HandoffCaller(pending_dir=workspace / "pending-calls",
                             timeout=handoff_timeout)

        def make_caller(log):
            return TracedCaller(base.bind(pursuit_id=log.pursuit_id,
                                          run_id=log.run_id), log)
        mode = "handoff"
    else:
        fake = FakeCaller(script or ci_script())

        def make_caller(log):
            return TracedCaller(fake, log)
        mode = "dry_run"

    pursuit = PursuitDir(workspace, "pur_demo")

    def demo_package(_pursuit):
        return IntakePackage(
            pursuit_id="pur_demo",
            docs=[IntakeDoc(path=DEMO_WORKBOOK, kind="rfp_main")],
            ramble=DEMO_RAMBLE.read_text(encoding="utf-8"))

    def gate0_policy(_pursuit):
        # replay/CI: the gate line records auto_approved=true, and the
        # assumption register stays UNCONFIRMED — a register stamped
        # confirmed under replay would claim a human reader it never had
        return {"decision": "auto_approved", "auto_approved": True}

    def gate1_policy(_pursuit):
        return {"decision": "approved"}

    def gate2_policy(p):
        dispositions = _canned_dispositions(p)
        return {"decision": ("approved_with_edits" if dispositions
                             else "approved"),
                "edits": ({"dispose": dispositions} if dispositions
                          else None)}

    adv = advance(pursuit, make_caller=make_caller, mode=mode,
                  kb_root=KB_ROOT, at=at, extras=_extras,
                  intake_package=demo_package, research_pack=DEMO_PACK,
                  workbook=DEMO_WORKBOOK, decide_gate0=gate0_policy,
                  decide_gate1=gate1_policy,
                  decide_gate2=gate2_policy, actor=ACTOR)
    result.ran_stages = adv.ran_stages
    result.problems.extend(adv.problems)
    if adv.status != "ok":
        # The slice supplies gate deciders and flags every gap, so the
        # driver's awaiting_* stops cannot occur here; failed/refused map.
        result.status = adv.status if adv.status == "refused" else "failed"
        return result

    ok, problems = verify_slice(pursuit)
    result.problems.extend(problems)
    if not ok:
        result.status = "failed"
        out("slice FAILED verification:")
        for problem in problems:
            out(f"  - {problem}")
        return result

    annotated = pursuit.read_artifact("drafts/annotated-draft.json")
    result.packaging = annotated["packaging"]
    result.cost_usd = _total_cost(pursuit.root)
    drafted = [s for s in annotated["sections"]
               if s["draft_status"] == "drafted"]
    findings = sum(len(s.get("findings", [])) for s in drafted)
    claims = sum(len(s.get("claims", [])) for s in drafted)
    out(f"slice ok: {len(annotated['sections'])} sections "
        f"({len(drafted)} drafted), {claims} claims audited, "
        f"{findings} findings, packaging={result.packaging}, "
        f"mode={mode}, cost=${result.cost_usd:.4f}")
    return result


def _all_records(root: Path) -> list[dict]:
    records: list[dict] = []
    runs = root / "runs"
    if runs.exists():
        for run_file in sorted(runs.glob("*/run.jsonl")):
            records.extend(read_run(run_file))
    return records


def _total_cost(root: Path) -> float:
    return round(sum(r.get("cost_usd", 0.0) for r in _all_records(root)
                     if r.get("record_type") == "agent_call"), 6)


def verify_slice(pursuit) -> tuple[bool, list[str]]:
    """The liveness guard (B34(14)): every run's trace is gapless and the
    annotated draft reconciles against the union of validation records.
    Absence or mismatch fails the slice — the acceptance command consumes
    the artifact, so it cannot be orphaned silently."""
    problems: list[str] = []
    runs = pursuit.root / "runs"
    run_files = sorted(runs.glob("*/run.jsonl")) if runs.exists() else []
    for index, run_file in enumerate(run_files):
        records = read_run(run_file)
        try:
            assert_seq_gapless(records)
        except Exception as exc:
            problems.append(f"{run_file.parent.name}: {exc}")
        if not any(r.get("record_type") == "run_end" for r in records):
            # A footerless HISTORICAL run is the honest record of a kill
            # that a later run resumed past; only a footerless FINAL run
            # means the slice never actually finished.
            if index == len(run_files) - 1:
                problems.append(
                    f"{run_file.parent.name}: the final run has no run_end "
                    f"footer — the slice died mid-flight")
    ok, consume_problems = consume_annotated(pursuit, _all_records(pursuit.root))
    problems.extend(consume_problems)
    return (not problems), problems


def run_slice_cli(args) -> int:
    workspace = Path(args.workspace)
    if args.fresh and workspace.exists():
        shutil.rmtree(workspace)
    result = run_slice(workspace, live=args.live, handoff=args.handoff,
                       handoff_timeout=args.handoff_timeout, at=args.at)
    return 0 if result.status == "ok" else 1


def register(sub) -> None:
    parser = sub.add_parser(
        "slice",
        help="the M1 vertical slice: demo package end-to-end, headless")
    parser.add_argument("--ci", action="store_true",
                        help="FakeCaller flavor (zero spend) — the make "
                             "slice default")
    flavor = parser.add_mutually_exclusive_group()
    flavor.add_argument("--live", action="store_true",
                        help="RFP_LIVE=1 flavor: the live model, real spend, "
                             "mode=live")
    flavor.add_argument("--handoff", action="store_true",
                        help="operator flavor (P20/B81): judgment through "
                             "pending-calls/ request/response files, "
                             "mode=handoff, zero spend")
    parser.add_argument("--handoff-timeout", type=float, default=900.0,
                        help="seconds to wait per judgment call before a "
                             "typed HandoffTimeout (handoff flavor only)")
    parser.add_argument("--workspace", default="pursuits/slice-ci",
                        help="workspace directory (CI default wipes with "
                             "--fresh)")
    parser.add_argument("--fresh", action="store_true",
                        help="wipe the workspace first (CI runs default this "
                             "via the Makefile)")
    parser.add_argument("--at", default=DEFAULT_AT,
                        help="injected clock for gates + the staleness check")
    parser.set_defaults(fn=run_slice_cli)
