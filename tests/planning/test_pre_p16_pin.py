"""The pre-P16 byte pin (P16/C0): the PROVEN xlsx path must parse
byte-identically to the record captured BEFORE any P16 change landed.

`test_plan_build_is_byte_deterministic` proves two runs of the SAME
code agree; it cannot see a regression that moves both runs together.
These digests were captured at 561acbc (1262 green, pre-P16) and are
the fixed point the whole phase is measured against: parse_workbook
and PARSER_VERSION are frozen for P16 — new document types get their
OWN parsers and version constants, and the xlsx bytes never move.

If this test fails, the change that broke it is out of P16's contract.
Do not regenerate the digests to make it pass — that is the false
close CLAUDE.md's honesty rule names. A deliberate xlsx parser change
is a NEW decision (PARSER_VERSION bump + B-entry + re-pin, together).
"""

import hashlib
import json
from pathlib import Path

import pytest

from engine.structure import parse_workbook
from tests.planning.fixtures.plans import run_planning_package

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"

# Captured 2026-08-28 at 561acbc, before any P16 commit.
CHAIN_PIN = {
    "slots.json": "9db1c8f0a69784eca5d77ec3fd92d7e5c345defda9f8a89dfc57b96bee086545",
    "plan.json": "888b94b08dbd9367bcde3f5ad91f8a03834b75432a5cef934b4009653a1b93f7",
}
PARSE_PIN = {
    "demo-twin.xlsx": "c640e5e1047471532df9a197ba4ef64f86398cd3988fd9b5d909b5e9fb7c3fb2",
    "structured-twin.xlsx": "52103473e79e5ee6b84d5d6823f7412e90e9ce54aeb5b8d8a3d1bfa7589b6669",
    "gapcase-twin.xlsx": "3af9fcb13662bd4bad64da71deedc403f8d3d1c588c4f6bfbccde48d426b329e",
    "nofill-twin.xlsx": "c8d83001888b616b71aae2fcf413baa75d40075901a2a966e4a4f0a20cb3a1f4",
}


def _canonical(parsed) -> bytes:
    """The parse result in the workspace writer's own serialization
    (indent=2, sort_keys) so the pin measures content, not formatting."""
    return json.dumps({
        "file": parsed.file,
        "source_mode": parsed.source_mode,
        "parser_version": parsed.parser_version,
        "source_sha256": parsed.source_sha256,
        "slot_count": parsed.slot_count,
        "slots": parsed.slots,
        "global_constraints": parsed.global_constraints,
    }, indent=2, sort_keys=True).encode("utf-8")


@pytest.mark.parametrize("twin", sorted(PARSE_PIN))
def test_xlsx_parse_matches_the_pre_p16_record(twin):
    digest = hashlib.sha256(_canonical(parse_workbook(FIXTURES / twin))).hexdigest()
    assert digest == PARSE_PIN[twin], (
        f"{twin}: parse output moved off the pre-P16 record — the xlsx "
        "path is frozen this phase (see module docstring before touching "
        "this pin)"
    )


def test_planned_artifacts_match_the_pre_p16_record(tmp_path):
    pursuit, _ = run_planning_package(tmp_path, package_id="xlsx", gate2=None)
    for name, expected in CHAIN_PIN.items():
        digest = hashlib.sha256((pursuit.root / name).read_bytes()).hexdigest()
        assert digest == expected, (
            f"{name}: full-chain bytes moved off the pre-P16 record"
        )
