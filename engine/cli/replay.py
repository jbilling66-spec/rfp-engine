"""`python -m engine replay <pursuit_id>` (P32c — A3's zero-spend half).

A replay runs a pursuit again, from its own inbox, under FakeCaller
(zero spend), into a separate replay workspace, with the firm KB's
knowledge of THAT pursuit withheld: every card the pursuit contributed
(`self_exclusion_set` — the purge question asked of a pursuit) is in
the `exclude` set that reaches every retrieval site, and every run
header says `mode: replay` / `replay_of: <pursuit_id>` so the runs
never enter a production series (O3) and are never mistaken for the
pursuit's own. Every gate is `auto_approved` — B22(13)'s reserved
literal, used here for the first time.

What this proves is HYGIENE, read off the trace: the exclusion fired
(lines name the withheld cards), nothing excluded was surfaced into a
result or opened, the headers and gate lines say what they are. What
it does not do is compare quality — A3's live replay, the v1 adapter
and the blind panel are the other half; the release gate's clause 4
stays `not_performed` until then (the owner's call, B143 §1).

The source pursuit is read (inbox, research pack) and never written.
A replay never resumes or overwrites: an existing replay of the same
pursuit in the chosen workspace refuses, and the operator picks `--out`.
No record file is written — the trace IS the record (B147 §3f).
"""

import sys
from dataclasses import dataclass, field
from pathlib import Path

from engine.cli.slice import (
    DEFAULT_AT,
    KB_ROOT,
    _canned_dispositions,
    _extras,
    verify_slice,
)
from engine.cli.slice_script import ci_script
from engine.contracts import ContractError
from engine.kb import KBStore, self_exclusion_set
from engine.llm import FakeCaller, TracedCaller
from engine.pipeline import advance
from engine.pipeline.inbox import package_from_inbox, resolve_targets
from engine.runlog import read_run
from engine.workspace import PursuitDir
from engine.workspace.lock import WorkspaceLocked, workspace_lock

ACTOR = "replay_runner"
REPLAYS_DIR = "replays"


@dataclass
class ReplayResult:
    status: str = "ok"  # ok | failed | refused
    problems: list[str] = field(default_factory=list)
    pursuit_id: str = ""
    replay_root: Path | None = None
    ran_stages: list[str] = field(default_factory=list)
    self_exclusion: list[str] = field(default_factory=list)
    excluded_lines: int = 0
    surfaced_excluded: list[str] = field(default_factory=list)
    opened_excluded: list[str] = field(default_factory=list)
    runs: int = 0
    headers_ok: bool = False
    gates_auto_approved: bool = False

    @property
    def hygienic(self) -> bool:
        """The replay ran to the end AND the trace shows the exclusion
        held, the headers name the replay, every gate is auto_approved.
        Not a quality verdict."""
        return (self.status == "ok" and not self.surfaced_excluded
                and not self.opened_excluded and self.headers_ok
                and self.gates_auto_approved)


def gate0_policy(_pursuit):
    # the gate line records auto_approved=true and the assumption
    # register stays UNCONFIRMED — a register stamped confirmed under
    # replay would claim a human reader it never had (the slice's rule)
    return {"decision": "auto_approved", "auto_approved": True}


def gate1_policy(_pursuit):
    return {"decision": "auto_approved", "auto_approved": True}


def gate2_policy(pursuit):
    # the approved J1 policy rides as edits (the gate applies edits under
    # any decision); the decision literal is the replay's own
    dispositions = _canned_dispositions(pursuit)
    return {"decision": "auto_approved", "auto_approved": True,
            "edits": ({"dispose": dispositions} if dispositions else None)}


def run_replay(workspace: Path, pursuit_id: str, *,
               out_workspace: Path | None = None, kb_root: Path = KB_ROOT,
               at: str = DEFAULT_AT, script: dict | None = None,
               out=print) -> ReplayResult:
    result = ReplayResult(pursuit_id=pursuit_id)
    source_root = Path(workspace) / pursuit_id
    inbox = source_root / "inbox"
    out_ws = (Path(out_workspace) if out_workspace
              else Path(workspace) / REPLAYS_DIR)
    replay_root = out_ws / pursuit_id

    def refuse(problem: str) -> ReplayResult:
        result.status = "refused"
        result.problems.append(problem)
        out(f"replay refused: {problem}")
        return result

    if not inbox.is_dir():
        return refuse(f"{source_root} has no inbox/ — nothing to replay")
    if replay_root.exists():
        return refuse(f"{replay_root} already exists — a replay never "
                      "resumes or overwrites; pass --out for a fresh one")
    try:
        resolved = resolve_targets(source_root)
        package = package_from_inbox(pursuit_id, source_root)
    except ContractError as exc:
        return refuse(str(exc))

    store = KBStore(kb_root)
    exclude = self_exclusion_set(store, pursuit_id)
    result.self_exclusion = sorted(exclude)
    fake = FakeCaller(script or ci_script())

    def make_caller(log):
        return TracedCaller(fake, log)

    pursuit = PursuitDir(out_ws, pursuit_id)
    result.replay_root = pursuit.root
    pack = inbox / "research-pack.md"
    adv = advance(
        pursuit, make_caller=make_caller, mode="replay", kb_root=kb_root,
        at=at, extras=_extras,
        intake_package=lambda _p: package,
        research_pack=pack if pack.exists() else None,
        targets=(resolved["targets"] if resolved["declared"] else None),
        core_doc=resolved["core"],
        workbook=(None if resolved["declared"]
                  else next(iter(resolved["targets"]), None)),
        decide_gate0=gate0_policy, decide_gate1=gate1_policy,
        decide_gate2=gate2_policy, actor=ACTOR,
        exclude=exclude, replay_of=pursuit_id)
    result.ran_stages = adv.ran_stages
    result.problems.extend(adv.problems)
    if adv.status != "ok":
        result.status = adv.status if adv.status == "refused" else "failed"
        out(f"replay {result.status} at {adv.stopped_at}: "
            + "; ".join(adv.problems))
        return result

    ok, problems = verify_slice(pursuit)  # the liveness guard, inherited
    result.problems.extend(problems)
    if not ok:
        result.status = "failed"
        out("replay FAILED verification:")
        for problem in problems:
            out(f"  - {problem}")
        return result

    _measure(result, pursuit, exclude)
    verdict = "ok" if result.hygienic else "FAILED hygiene"
    out(f"replay {verdict}: {pursuit_id} -> {pursuit.root}; "
        f"{result.runs} runs, mode=replay; "
        f"self-exclusion {len(result.self_exclusion)} card(s); "
        f"withheld on {result.excluded_lines} line(s); "
        f"surfaced {len(result.surfaced_excluded)}, "
        f"opened {len(result.opened_excluded)}; "
        f"headers {'ok' if result.headers_ok else 'WRONG'}; "
        f"gates {'auto_approved' if result.gates_auto_approved else 'NOT auto_approved'}")
    return result


def _measure(result: ReplayResult, pursuit, exclude: frozenset) -> None:
    """Read the verdict off the replay's own run logs — never off what
    the runner believes it passed."""
    headers: list[dict] = []
    gates: list[dict] = []
    lines: list[dict] = []
    run_files = sorted((pursuit.root / "runs").glob("*/run.jsonl"))
    for run_file in run_files:
        for record in read_run(run_file):
            kind = record.get("record_type")
            if kind == "run_start":
                headers.append(record["run"])
            elif kind == "gate":
                gates.append(record["gate"])
            elif kind == "kb_retrieval":
                lines.append(record["kb"])
    result.runs = len(run_files)
    result.headers_ok = bool(headers) and all(
        h.get("mode") == "replay" and h.get("replay_of") == result.pursuit_id
        for h in headers)
    result.gates_auto_approved = bool(gates) and all(
        g.get("decision") == "auto_approved" and g.get("auto_approved") is True
        for g in gates)
    result.excluded_lines = sum(
        1 for kb in lines if set(kb.get("excluded") or ()) & exclude)
    result.surfaced_excluded = sorted({
        k for kb in lines for k in (kb.get("cards_returned") or ())
        if k in exclude})
    result.opened_excluded = sorted({
        k for kb in lines for k in (kb.get("cards_opened") or ())
        if k in exclude})


def run_replay_cli(args) -> int:
    workspace = Path(args.workspace)
    out_ws = Path(args.out) if args.out else workspace / REPLAYS_DIR
    try:
        lock = workspace_lock(out_ws, holder="engine replay")
    except WorkspaceLocked as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    with lock:
        result = run_replay(workspace, args.pursuit_id, out_workspace=out_ws,
                            at=args.at)
    if result.status == "refused":
        return 2
    return 0 if result.hygienic else 1


def register(sub) -> None:
    parser = sub.add_parser(
        "replay",
        help="re-run a pursuit under FakeCaller with its own KB "
             "contributions withheld (mode=replay, zero spend) — the "
             "hygiene proof, not a quality comparison")
    parser.add_argument("pursuit_id", help="the pursuit to replay")
    parser.add_argument("--workspace", default="pursuits/slice-ci",
                        help="workspace holding the pursuit (read only)")
    parser.add_argument("--out", default=None,
                        help="replay workspace (default <workspace>/replays); "
                             "an existing replay of the pursuit there refuses")
    parser.add_argument("--at", default=DEFAULT_AT,
                        help="injected clock for gates + the staleness check")
    parser.set_defaults(fn=run_replay_cli)
