"""schemas/draft.schema.json — prose carries no control characters
(P26a Group B, P2-29b): the contract is the last line behind the wire's
entry-side refusal, so a raw write through write_artifact refuses too."""

import json
from pathlib import Path

import pytest

from engine.contracts import ContractError, validate

REPO = Path(__file__).resolve().parents[2]


def _minimal(prose: str) -> dict:
    # the smallest envelope the schema accepts, from a committed fixture's
    # shape: one Path-B section carrying `prose`
    schema = json.loads((REPO / "schemas" / "draft.schema.json").read_text())
    req = schema["required"]
    base = {k: None for k in req}
    base.update({"pursuit_id": "pur_p", "plan_sha256": "a" * 64,
                 "status": "complete", "revision_n": 0, "sections": [
                     {"section_id": "s1", "title": "T", "section_type": "t",
                      "status": "drafted", "prose": prose,
                      "cards_cited": []}]})
    return {k: v for k, v in base.items() if v is not None}


def test_clean_prose_validates_and_control_characters_refuse():
    validate("draft", _minimal("Plain prose.\nSecond line.\tTabbed."))
    with pytest.raises(ContractError):
        validate("draft", _minimal("bad\x0bchar"))
    with pytest.raises(ContractError):
        validate("draft", _minimal("nul\x00"))
