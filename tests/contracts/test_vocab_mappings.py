"""The two vocab mapping tables stay total over their enum domains (B7).

If a schema enum gains a value, these tests fail until the mapping says
where it goes — an unmapped vocabulary value is how two streams silently
stop joining.
"""

import json
from pathlib import Path

SCHEMAS = Path(__file__).resolve().parents[2] / "schemas"


def _load(name: str) -> dict:
    return json.loads((SCHEMAS / name).read_text(encoding="utf-8"))


def test_gap_mapping_is_total():
    mapping = _load("mappings/gap-vocab.json")
    log_reasons = set(
        _load("run-log.schema.json")["properties"]["gap"]["properties"]["reason"]["enum"]
    )
    plan_kinds = set(
        _load("pursuit-plan.schema.json")["properties"]["sections"]["items"]["properties"][
            "gaps"
        ]["items"]["properties"]["kind"]["enum"]
    )
    assert set(mapping["reason_to_kind"]) == log_reasons
    assert set(mapping["reason_to_kind"].values()) <= plan_kinds
    assert set(mapping["kind_to_default_reason"]) == plan_kinds
    assert set(mapping["kind_to_default_reason"].values()) <= log_reasons


def test_outcome_mapping_is_total():
    mapping = _load("mappings/outcome-vocab.json")
    feedback_results = set(
        _load("feedback-event.schema.json")["properties"]["outcome"]["properties"]["result"][
            "enum"
        ]
    )
    card_outcomes = set(_load("kb-card.schema.json")["properties"]["outcome"]["enum"])
    assert set(mapping["feedback_to_card"]) == feedback_results
    assert set(mapping["feedback_to_card"].values()) <= card_outcomes
