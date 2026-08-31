"""P19 acceptance — docs/graph/artifact-flow.md equals the code it describes (B79).

Tables are two-direction equality against _KINDS, schemas/, the run-log kind
enum, and PursuitDir.SUBDIRS. The flowchart alone is containment-only (B79 D3:
no single code constant maps stages to filenames), and the doc says exactly
that. A red here means code and map diverged: fix the code first, then the row.
"""

import json
import re
from pathlib import Path

from engine.contracts.validate import _KINDS
from engine.workspace import pursuit as pursuit_mod

REPO = Path(__file__).resolve().parents[2]
DOC = REPO / "docs" / "graph" / "artifact-flow.md"
SCHEMAS = REPO / "schemas"


def _table_with_header(header0: str) -> list[list[str]]:
    tables = []
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


def test_kinds_table_equals_validate_kinds():
    doc = {row[0].strip("`"): row[1].strip("`") for row in _table_with_header("kind")}
    assert doc == _KINDS, (
        f"kinds drift — doc-only: {sorted(set(doc) - set(_KINDS))}; "
        f"code-only: {sorted(set(_KINDS) - set(doc))}; "
        f"value mismatches: {sorted(k for k in doc.keys() & _KINDS.keys() if doc[k] != _KINDS[k])}"
    )


def test_schema_files_on_disk_equal_kinds_values():
    on_disk = {p.name for p in SCHEMAS.glob("*.schema.json")}
    assert on_disk == set(_KINDS.values()), (
        f"schemas/ drift — on disk only: {sorted(on_disk - set(_KINDS.values()))}; "
        f"in _KINDS only: {sorted(set(_KINDS.values()) - on_disk)}"
    )


def test_runlog_artifact_kinds_match_schema_enum():
    schema = json.loads((SCHEMAS / "run-log.schema.json").read_text())
    enum = set(
        schema["properties"]["artifact"]["properties"]["kind"]["enum"]
    )
    listing = re.search(r"\n(`\w+`(?: · `\w+`)+)\n", DOC.read_text())
    assert listing, "artifact-flow.md has no run-log kind listing"
    doc = set(re.findall(r"`(\w+)`", listing.group(1)))
    assert doc == enum, (
        f"run-log kind drift — doc-only: {sorted(doc - enum)}; "
        f"schema-only: {sorted(enum - doc)}"
    )


def test_workspace_subdirs_table_equals_pursuit_constant():
    doc = {row[0].strip("`") for row in _table_with_header("subdir")}
    code = set(pursuit_mod.SUBDIRS)
    assert doc == code, (
        f"workspace-layout drift — doc-only: {sorted(doc - code)}; "
        f"code-only: {sorted(code - doc)}"
    )


def test_flowchart_file_nodes_exist_in_engine_source():
    block = re.search(r"```mermaid\n(.*?)```", DOC.read_text(), re.S)
    assert block, "artifact-flow.md has no mermaid block"
    quoted = re.findall(r'\["([^"]+)"\]', block.group(1))
    assert quoted, "the flowchart has no quoted file nodes"
    source = "\n".join(
        py.read_text() for py in (REPO / "engine").rglob("*.py")
    )
    for label in quoted:
        # a node label may carry a parenthetical; the file token is the part
        # before any " (" annotation, trailing "/" allowed for directories
        token = label.split(" (")[0].rstrip("/").split("/")[-1]
        assert token in source, (
            f"flowchart node {label!r} names {token!r}, which appears nowhere in engine source"
        )
