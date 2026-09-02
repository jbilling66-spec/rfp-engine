"""Every schema in schemas/ is valid JSON Schema 2020-12 and loadable.

The lockstep tests (schema <-> pydantic contract) grow alongside
engine/contracts; this file is the floor: the contract *files* are
well-formed before anything imports them.
"""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

SCHEMAS_DIR = Path(__file__).resolve().parents[2] / "schemas"
SCHEMA_FILES = sorted(SCHEMAS_DIR.glob("*.schema.json"))

EXPECTED = {
    "access-log.schema.json",
    "annotated-draft.schema.json",
    "bid-brief.schema.json",
    "canonical-doc.schema.json",
    "draft.schema.json",
    "eval-case.schema.json",
    "eval-results.schema.json",
    "feedback-event.schema.json",
    "hand-fill.schema.json",
    "kb-card.schema.json",
    "kb-proposal.schema.json",
    "manifest.schema.json",
    "metric-definition.schema.json",
    "pursuit-plan.schema.json",
    "run-log.schema.json",
    "slots.schema.json",
    "submission-bundle.schema.json",
    "target-slot.schema.json",
    "template-fill-facts.schema.json",
    "writeback-facts.schema.json",
}


def test_all_contracts_present():
    assert {p.name for p in SCHEMA_FILES} == EXPECTED


@pytest.mark.parametrize("path", SCHEMA_FILES, ids=lambda p: p.name)
def test_schema_is_valid_2020_12(path):
    schema = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
