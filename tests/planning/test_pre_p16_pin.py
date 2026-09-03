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
# Re-captured 2026-09-03 at 94b134f for PARSER_VERSION 2.1.0 (P26b-1, B112 §1b:
# formula question cells parse from cached values — the deliberate bump this
# docstring names; the digests moved with parser_version, the slots did not).
CHAIN_PIN = {
    "slots.json": "b2d41bc508788ee22441377bffd88c5e730faea50e50660dc9d464ce8bffaa3e",
    "plan.json": "888b94b08dbd9367bcde3f5ad91f8a03834b75432a5cef934b4009653a1b93f7",
}
PARSE_PIN = {
    "demo-twin.xlsx": "6dd6363aecf37e7ec33d72b2a491f1c22af6629197b1a0689a23648da8e45f33",
    "structured-twin.xlsx": "b19abd652cf8672295d1c30b78328cd5cae6a7cd36c86446ad4973d8a3cff7c9",
    "gapcase-twin.xlsx": "2906ed0060dbdc782d3118f3c1047bbbd570465ee5a5d0ef64243be9151a6948",
    "nofill-twin.xlsx": "0c73e96149417d1bb53d1c33ea0ce8cd8ae040f8959e44f48f78aaef1d95ee4e",
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
