"""P19 acceptance — docs/graph/doors.md equals the doors the engine exposes (B79).

The door index is compared two-direction against the LIVE route table
(create_app on a throwaway workspace), the Makefile's parsed targets, the CLI's
introspected argparse tree (build_parser, B79 D4), and the repo's __main__
guards. A red here means a door moved without its map row: fix the code first,
then the named row.
"""

import argparse
import re
from pathlib import Path

from fastapi.routing import APIRoute
from starlette.testclient import TestClient

from engine.cli.main import build_parser
from engine.web.server import create_app

REPO = Path(__file__).resolve().parents[2]
DOC = REPO / "docs" / "graph" / "doors.md"

# The framework's own furniture, deliberately outside the doc's table. Closed
# set: if FastAPI ever grows a default route — or someone adds a router,
# websocket, or HEAD handler — this pin fails loudly instead of silently
# widening the exclusion.
FURNITURE = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc", "/static"}


def _rows_with_header(header0: str) -> list[list[str]]:
    rows = []
    text = DOC.read_text().splitlines()
    for i, line in enumerate(text):
        if line.startswith("|") and [c.strip() for c in line.strip("|").split("|")][0] == header0:
            for later in text[i + 1 :]:
                if not later.startswith("|"):
                    break
                cells = [c.strip() for c in later.strip("|").split("|")]
                if all(set(c) <= {"-", " "} for c in cells):
                    continue
                rows.append(cells)
    assert rows, f"no table rows under a '{header0}' header in doors.md"
    return rows


def _raising_make_caller(log):
    raise AssertionError("offline: the doors test must never construct a caller")


def test_route_table_equals_app_routes(tmp_path):
    app = create_app(tmp_path / "ws", make_caller=_raising_make_caller)
    with TestClient(app):
        live = {
            (m, r.path)
            for r in app.routes
            if isinstance(r, APIRoute)
            for m in r.methods
        }
        other = {getattr(r, "path", str(r)) for r in app.routes if not isinstance(r, APIRoute)}
    assert other == FURNITURE, (
        f"framework furniture moved — unexpected: {sorted(other - FURNITURE)}; "
        f"vanished: {sorted(FURNITURE - other)}"
    )
    doc = {(row[0], row[1].strip("`")) for row in _rows_with_header("method")}
    assert doc == live, (
        f"door drift — in doc only: {sorted(doc - live)}; "
        f"live but unmapped: {sorted(live - doc)}"
    )


def test_make_targets_table_equals_makefile():
    targets = set(
        re.findall(r"^([A-Za-z][\w-]*)\s*:(?!=)", (REPO / "Makefile").read_text(), re.M)
    )
    doc = {row[0].strip("`") for row in _rows_with_header("target")}
    assert doc == targets, (
        f"make-target drift — doc-only: {sorted(doc - targets)}; "
        f"Makefile-only: {sorted(targets - doc)}"
    )


def _walk(parser, prefix=()):
    out = []
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, sub in action.choices.items():
                path = prefix + (name,)
                deeper = _walk(sub, path)
                out.extend(deeper if deeper else [path])
    return out


def test_cli_table_equals_argparse_tree():
    tree = {" ".join(p) for p in _walk(build_parser())}
    doc = {row[0].strip("`") for row in _rows_with_header("command")}
    assert doc == tree, (
        f"CLI drift — doc-only: {sorted(doc - tree)}; "
        f"argparse-only: {sorted(tree - doc)}"
    )


def test_main_module_doors_are_all_documented():
    # tools/ joined the sweep at B87 §2: tools/public_cut.py carries a
    # guard the engine-only glob could never see.
    guards = {
        ".".join(py.relative_to(REPO).with_suffix("").parts)
        for scope in ("engine", "tools")
        for py in (REPO / scope).rglob("*.py")
        if 'if __name__ == "__main__"' in py.read_text()
    }
    if (REPO / "engine" / "__main__.py").exists():
        guards.add("engine")  # python -m engine: the dispatcher door
    doc = {row[0].strip("`") for row in _rows_with_header("module")}
    assert doc == guards, (
        f"__main__ door drift — doc-only: {sorted(doc - guards)}; "
        f"code-only: {sorted(guards - doc)}"
    )


def test_regeneration_doors_resolve():
    """B87 §2: every `from X import f` one-liner the regeneration-doors
    section names must resolve to a real function (one direction — a new
    regeneration function is added to the doc deliberately)."""
    import importlib

    pairs = re.findall(r"`from ([\w.]+) import (\w+)`", DOC.read_text())
    assert pairs, "the regeneration-doors section names no importable door"
    for mod_name, fn in pairs:
        mod = importlib.import_module(mod_name)
        assert callable(getattr(mod, fn, None)), (
            f"doors.md names a regeneration door that does not resolve: "
            f"from {mod_name} import {fn}")
