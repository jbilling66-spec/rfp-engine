"""Thin CLI dispatcher — one module per command group as command groups
arrive with their stages (the v1 41-subcommand __main__ monolith is the
counterexample this layout answers)."""

import argparse
import sys
from pathlib import Path


def _cmd_version(_args) -> int:
    from engine.version import engine_version
    print(engine_version())
    return 0


def _cmd_check_run(args) -> int:
    from engine.contracts import ContractError, check_runlog_payloads, validate
    from engine.runlog import assert_seq_gapless, read_run_report

    try:
        records, torn = read_run_report(Path(args.path))
    except ContractError as e:  # a torn or invalid line before the tail
        print(f"CORRUPT: {e}", file=sys.stderr)
        return 1
    if torn:
        print(f"TORN: {torn} — the next resume repairs it (P0-14 runbook)",
              file=sys.stderr)
        return 1
    try:
        for record in records:
            validate("run_log", record)
            check_runlog_payloads(record)
        assert_seq_gapless(records)
    except ContractError as e:
        print(f"INVALID: {e}", file=sys.stderr)
        return 1
    print(f"ok: {len(records)} records, seq gapless, all lines valid")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="engine")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("version").set_defaults(fn=_cmd_version)

    check = sub.add_parser("check-run", help="validate a run.jsonl")
    check.add_argument("path")
    check.set_defaults(fn=_cmd_check_run)

    from engine.cli.evals import register as register_evals
    from engine.cli.intake import register as register_intake
    from engine.cli.kb import register as register_kb
    from engine.cli.serve import register as register_serve
    from engine.cli.slice import register as register_slice
    register_kb(sub)
    register_intake(sub)
    register_slice(sub)
    register_serve(sub)
    register_evals(sub)

    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.fn(args)
