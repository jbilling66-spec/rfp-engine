"""P19 acceptance — docs/graph/modules.md equals the code it describes (B79).

The doc is the single source (B79 D1): these tests parse its tables and mermaid
block directly and compare against an AST walk of engine/, both directions. A
red here means code and map diverged: fix the code first, then the named row.
"""

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ENGINE = REPO / "engine"
DOC = REPO / "docs" / "graph" / "modules.md"

# The B79 D2 collapse rule — stated identically in the doc's rule paragraph.
DOORS = {"cli", "web", "evals", "assistant"}
FOUNDATIONS = {"contracts", "runlog", "llm", "workspace"}


def _packages() -> set[str]:
    return {p.name for p in ENGINE.iterdir() if p.is_dir() and p.name != "__pycache__"}


def _import_edges() -> set[tuple[str, str]]:
    """Edge A->B iff any file under engine/A/ imports engine.B at ANY scope."""
    edges = set()
    pkgs = _packages()
    for pkg in pkgs:
        for py in (ENGINE / pkg).rglob("*.py"):
            for node in ast.walk(ast.parse(py.read_text())):
                if isinstance(node, ast.Import):
                    targets = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    targets = [node.module]
                else:
                    continue
                for t in targets:
                    parts = t.split(".")
                    if parts[0] == "engine" and len(parts) > 1 and parts[1] in pkgs:
                        if parts[1] != pkg:
                            edges.add((pkg, parts[1]))
    return edges


def _table_with_header(header0: str) -> list[list[str]]:
    tables, current = [], []
    text = DOC.read_text().splitlines()
    for i, line in enumerate(text):
        if line.startswith("|") and [c.strip() for c in line.strip("|").split("|")][0] == header0:
            rows = []
            for later in text[i + 1 :]:
                if not later.startswith("|"):
                    break
                cells = [c.strip() for c in later.strip("|").split("|")]
                if all(set(c) <= {"-", " "} for c in cells):
                    continue
                rows.append(cells)
            tables.append(rows)
    assert len(tables) == 1, f"expected exactly one table headed '{header0}', found {len(tables)}"
    return tables[0]


def _mermaid_edges() -> set[tuple[str, str]]:
    block = re.search(r"```mermaid\n(.*?)```", DOC.read_text(), re.S)
    assert block, "modules.md has no mermaid block"
    return set(re.findall(r"^\s*(\w+)\s*-->\s*(\w+)", block.group(1), re.M))


def test_package_inventory_matches_engine_dirs():
    doc = {row[0] for row in _table_with_header("package")}
    code = _packages()
    assert doc == code, (
        f"inventory drift — in doc only: {sorted(doc - code)}; "
        f"in engine/ only: {sorted(code - doc)}"
    )


def test_drawn_import_graph_matches_ast_under_the_stated_rule():
    drawn_expected = {
        (a, b)
        for a, b in _import_edges()
        if a not in DOORS and b not in FOUNDATIONS
    }
    drawn_doc = _mermaid_edges()
    assert drawn_doc == drawn_expected, (
        f"import-graph drift — drawn but not real: {sorted(drawn_doc - drawn_expected)}; "
        f"real but not drawn: {sorted(drawn_expected - drawn_doc)}"
    )


def test_door_fanout_and_foundation_fanin_tables_match_ast():
    edges = _import_edges()
    fanout_doc = {
        (row[0], target)
        for row in _table_with_header("door")
        for target in row[1].replace(" ", "").split(",")
    }
    fanout_expected = {(a, b) for a, b in edges if a in DOORS}
    assert fanout_doc == fanout_expected, (
        f"door fan-out drift — doc-only: {sorted(fanout_doc - fanout_expected)}; "
        f"code-only: {sorted(fanout_expected - fanout_doc)}"
    )
    fanin_doc = {
        (source, row[0])
        for row in _table_with_header("foundation")
        for source in row[1].replace(" ", "").split(",")
    }
    fanin_expected = {(a, b) for a, b in edges if b in FOUNDATIONS and a not in DOORS}
    assert fanin_doc == fanin_expected, (
        f"foundation fan-in drift — doc-only: {sorted(fanin_doc - fanin_expected)}; "
        f"code-only: {sorted(fanin_expected - fanin_doc)}"
    )
    covered = (
        {(a, b) for a, b in edges if a not in DOORS and b not in FOUNDATIONS}
        | fanout_expected
        | fanin_expected
    )
    assert covered == edges, f"edges escaping diagram+tables: {sorted(edges - covered)}"


def _caller_sites() -> list[tuple[str, str, str]]:
    """(file, agent, attr) per detected seam call — B79 D5: a call on attr
    call/call_for carrying tier= with a literal or module-constant agent name,
    engine/ minus engine/llm/ (the seam's own internals)."""
    sites = []
    for py in ENGINE.rglob("*.py"):
        if py.relative_to(ENGINE).parts[0] == "llm":
            continue
        tree = ast.parse(py.read_text())
        consts = {
            t.id: n.value.value
            for n in ast.walk(tree)
            if isinstance(n, ast.Assign)
            and isinstance(n.value, ast.Constant)
            and isinstance(n.value.value, str)
            for t in n.targets
            if isinstance(t, ast.Name)
        }
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("call", "call_for")
                and any(k.arg == "tier" for k in node.keywords)
                and node.args
            ):
                arg = node.args[0]
                agent = None
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    agent = arg.value
                elif isinstance(arg, ast.Name) and arg.id in consts:
                    agent = consts[arg.id]
                if agent:
                    sites.append((str(py.relative_to(REPO)), agent, node.func.attr))
    return sorted(sites)


def test_caller_seam_table_matches_detected_call_sites():
    detected = _caller_sites()
    assert len(detected) == 19, f"seam site count moved: {len(detected)} (expected 19)"
    assert sum(1 for _, _, attr in detected if attr == "call_for") == 1
    doc_rows = _table_with_header("file")
    doc_sites = sorted(
        (row[0].strip("`"), row[1].strip("`"), row[2])
        for row in doc_rows
        for _ in range(int(row[3]))
    )
    assert doc_sites == detected, (
        f"caller-seam drift — doc-only: {sorted(set(doc_sites) - set(detected))}; "
        f"code-only: {sorted(set(detected) - set(doc_sites))}"
    )


def test_every_prompts_agent_dir_is_named():
    text = DOC.read_text()
    prompt_dirs = {
        p.name for p in (REPO / "prompts").iterdir() if p.is_dir() and p.name != "shared"
    }
    agents = {agent for _, agent, _ in _caller_sites()}
    for d in prompt_dirs:
        assert d in text, f"prompts/{d}/ is not named in modules.md"
    # The one agent<->prompts-dir exception (B79 D5), pinned so a false 1:1
    # claim can never come back:
    assert "steward_assistant" in agents and "assistant" in prompt_dirs
    assert "prompts/assistant/prompt.md" in text


def test_stage_order_matches_driver_source():
    hits = []
    tree = ast.parse((ENGINE / "pipeline" / "driver.py").read_text())
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "StageRun"
            and len(node.args) >= 4
            and isinstance(node.args[3], ast.Constant)
        ):
            hits.append((node.lineno, node.args[3].value))
    order = []
    for _, stage in sorted(hits):
        if stage not in order:
            order.append(stage)
    span = re.search(r"`(\w+(?: -> \w+)+)`", DOC.read_text())
    assert span, "modules.md has no stage-order code span"
    assert span.group(1).split(" -> ") == order, (
        f"stage-order drift — doc says {span.group(1)!r}, driver.py says {' -> '.join(order)!r}"
    )
