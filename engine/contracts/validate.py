"""Schema validation facade. schemas/ is the contract (spec rule 4).

jsonschema is the enforcement layer at every artifact write. Typed pydantic
models grow per stage as stages land, each lockstep-tested against the same
schema files — no big-bang model mirror to drift.

check_runlog_payloads is the code half of B10: the schema requires each
record type's payload to be PRESENT; this check additionally rejects
FOREIGN exclusive payloads (a gate object on an agent_call line).
"""

import json
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

SCHEMAS_DIR = Path(__file__).resolve().parents[2] / "schemas"

_KINDS = {
    "bid_brief": "bid-brief.schema.json",
    "pursuit_plan": "pursuit-plan.schema.json",
    "feedback_event": "feedback-event.schema.json",
    "kb_card": "kb-card.schema.json",
    "run_log": "run-log.schema.json",
    "eval_case": "eval-case.schema.json",
    "metric_definition": "metric-definition.schema.json",
    "target_slot": "target-slot.schema.json",
    "manifest": "manifest.schema.json",
    "draft": "draft.schema.json",
    "annotated_draft": "annotated-draft.schema.json",
    "target_slots": "slots.schema.json",
    "access_log": "access-log.schema.json",
    "writeback_facts": "writeback-facts.schema.json",
    "template_fill_facts": "template-fill-facts.schema.json",
    "submission_bundle": "submission-bundle.schema.json",
    "eval_results": "eval-results.schema.json",
    "kb_proposal": "kb-proposal.schema.json",
    "canonical_doc": "canonical-doc.schema.json",
    "hand_fill": "hand-fill.schema.json",
}


class ContractError(ValueError):
    """An artifact violated its schema or the run-log payload discipline."""


@lru_cache(maxsize=None)
def _validator(kind: str) -> Draft202012Validator:
    schema = json.loads((SCHEMAS_DIR / _KINDS[kind]).read_text(encoding="utf-8"))
    return Draft202012Validator(schema)


def validate(kind: str, obj: dict) -> None:
    if kind not in _KINDS:
        raise ContractError(f"unknown contract kind {kind!r}; known: {sorted(_KINDS)}")
    try:
        _validator(kind).validate(obj)
    except ValidationError as e:
        raise ContractError(f"{kind}: {e.message} (at {list(e.absolute_path)})") from e


# The seven mutually exclusive payload objects on a run-log line.
_EXCLUSIVE = {"run", "kb", "gate", "validation", "gap", "artifact", "error"}

_ALLOWED = {
    "run_start": {"run"},
    "run_end": {"run"},
    "cost_rollup": {"run"},
    "stage_start": set(),
    "stage_end": set(),
    "agent_call": set(),
    "tool_call": set(),
    "kb_retrieval": {"kb"},
    "gate": {"gate"},
    "validation": {"validation"},
    "gap": {"gap"},
    "artifact": {"artifact"},
    "error": {"error"},
}


def check_runlog_payloads(record: dict) -> None:
    record_type = record.get("record_type")
    foreign = (_EXCLUSIVE - _ALLOWED.get(record_type, set())) & set(record)
    if foreign:
        raise ContractError(
            f"run-log {record_type!r} line carries foreign payload(s) {sorted(foreign)}"
        )
