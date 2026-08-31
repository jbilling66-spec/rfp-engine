"""`engine eval` (B40/D3): the eval harness + release gates, CLI-only —
never the web job runner (single worker; a long eval would starve every
pursuit behind it). Default run is fully offline and spends nothing:
deterministic lanes measure fresh, model lanes read recorded baselines
behind fingerprint checks. Writes the release record and exits nonzero
while any blocking bar is unmet — RED here is the honest mid-phase state
(B40/D4), not a breakage; the record names exactly what blocked.

The live re-baseline arm (`--rebaseline ... --live`, cX per B40/D6) is
the one path here that can bill money. It is gated three ways: `--live`
is mandatory (a scripted re-baseline would record the script's recall
under the model's name), LiveCaller construction refuses without
RFP_LIVE=1 + a complete price table + a key, and a shared SpendBudget
bounds the whole invocation rather than each run inside it.
"""

from datetime import datetime, timezone
from pathlib import Path

from engine.evals import run as _run
from engine.evals.release import RELEASES_DIR, build_record, write_record


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_rebaseline_cli(args) -> int:
    """Re-measure the model-scored suites live and write their baselines.

    Both suites share one auditor prompt, so hardening it stales BOTH
    baselines — which is why `all` is the default target and why the
    close commit carries the prompt edit and both re-measures together
    (B40/D6). Leaving one stale would leave `make eval` refusing on a
    fingerprint, having already spent the money.
    """
    from engine.evals.rebaseline import (SUITES, RebaselineRefused,
                                         DEFAULT_WORKSPACE, rebaseline)
    from engine.llm import (LiveCaller, SpendBudget, TracedCaller,
                            load_env_file, model_prices)
    from engine.version import engine_version

    if not args.live:
        print("REFUSED: --rebaseline requires --live. Under a scripted "
              "caller the extractor returns whatever the script says, so "
              "the recorded number would be the script's recall wearing "
              "the model's name (B33(1)) — a baseline nobody measured.")
        return 1

    targets = (sorted(SUITES) if args.rebaseline == "all"
               else [args.rebaseline])
    root = Path(__file__).resolve().parents[2]
    load_env_file(root / ".env")  # the one sanctioned .env read (B34(22))
    try:
        live_caller = LiveCaller()  # refusals are named, and spend nothing
    except Exception as exc:
        print(f"rebaseline --live refused: {exc}")
        return 1

    prices = model_prices()["prices"]
    # ONE budget across every suite in this invocation: each suite opens
    # its own run, and a per-run ceiling would let the worst case scale
    # with the number of suites (recorded decision, 2026-08-10).
    budget = SpendBudget()

    def make_caller(log):
        return TracedCaller(live_caller, log, prices=prices, budget=budget)

    at = args.at or _now_iso()
    workspace = Path(args.workspace) if args.workspace else DEFAULT_WORKSPACE
    version = engine_version()
    print(f"live re-baseline: {', '.join(targets)}  (workspace {workspace})")
    written = []
    for name in targets:
        try:
            result = rebaseline(name, make_caller=make_caller,
                                workspace=workspace, at=at,
                                engine_version=version)
        except RebaselineRefused as exc:
            print(f"REFUSED: {exc}")
            return 1
        written.append(result)
        print(f"    baseline: {result['baseline_path']}")
        print(f"    run log:  {result['run_path']}")

    print(f"spend this invocation: ${budget.spent_usd:.4f} "
          f"over {budget.calls} calls (guard: ${budget.total_usd:.2f} / "
          f"{budget.max_calls} calls)")
    print(f"re-baselined {len(written)} suite(s) — "
          f"run `make eval` to score the release record against them")
    return 0


def run_eval_cli(args) -> int:
    from engine.metrics.resolver import UnknownMetric
    from engine.metrics.views import validate_views
    from engine.version import engine_version

    if args.rebaseline:
        return run_rebaseline_cli(args)
    if args.live:
        print("REFUSED: --live only applies to --rebaseline. The default "
              "eval run is offline by construction and spends nothing.")
        return 1

    # "unknown metric_id fails build" (R6): no CI pipeline exists, so the
    # build that fails is this command and `make check`. Both run the
    # same check, so a chart naming a metric the registry lacks cannot
    # reach a screen through either door.
    try:
        validate_views()
    except UnknownMetric as bad:
        print(f"REFUSED: {bad}")
        return 1

    # The registry is read at call time, never bound at import: lanes
    # arrive commit by commit (c5-c11) and tests substitute them.
    suites = _run.SUITES
    if args.suite:
        if args.suite not in suites:
            print(f"unknown suite {args.suite!r} — known: "
                  f"{', '.join(sorted(suites))}")
            return 1
        lanes = {args.suite: suites[args.suite]()}
    else:
        lanes = {name: lane() for name, lane in sorted(suites.items())}

    version = engine_version()
    at = args.at or _now_iso()
    record = build_record(lanes, engine_version=version, at=at)

    for name, entry in record["suites"].items():
        line = f"  {name:14s} {entry['status']:16s} basis={entry['basis']}"
        detail = entry.get("detail")
        print(line + (f"  ({detail})" if detail and
                      entry["status"] != "pass" else ""))
    for gate in record["gates"]:
        mark = {"pass": "ok", "fail": "FAIL",
                "not_performed": f"not performed -> {gate.get('closer')}"}
        print(f"  gate {gate['clause']}: {mark[gate['status']]}")

    if args.suite:
        # A single-lane run never writes the record — a record carrying
        # one suite would misrepresent the release state.
        entry = record["suites"][args.suite]
        return 0 if entry["status"] == "pass" else 1

    path = write_record(record, args.out or RELEASES_DIR)
    print(f"release record: {path}")
    if record["blocking_failures"]:
        print(f"BLOCKING: {', '.join(record['blocking_failures'])} — "
              f"cannot promote (E7 clause 1, no waiver path)")
        return 1
    print("eval_pass_state: true")
    return 0


def register(sub) -> None:
    parser = sub.add_parser(
        "eval",
        help="eval harness + release gates: writes the release record, "
             "exits nonzero while a blocking bar is unmet")
    parser.add_argument("--suite", default=None,
                        help="run ONE lane and exit by its status; no "
                             "record is written")
    parser.add_argument("--at", default=None,
                        help="injected clock for the record (tests; "
                             "default = now)")
    parser.add_argument("--out", default=None,
                        help="releases directory override (tests; default "
                             "docs/releases/)")
    parser.add_argument("--rebaseline", default=None,
                        choices=("poison", "claim_extraction", "all"),
                        help="re-measure the model-scored suites LIVE and "
                             "write their baselines; requires --live and "
                             "real spend (default target 'all' — one prompt "
                             "feeds both suites)")
    parser.add_argument("--live", action="store_true",
                        help="RFP_LIVE=1 flavor: the live model, real "
                             "spend. Only meaningful with --rebaseline")
    parser.add_argument("--workspace", default=None,
                        help="where the re-baseline run logs are written "
                             "(default pursuits/eval-live/)")
    parser.set_defaults(fn=run_eval_cli)
