"""The one whole-file JSON reader for records (P26b-2, M-30).

A hand-authored or half-edited record file is EVIDENCE, not noise: the
proposal inbox used to 500 on one such file and hide every other
steward decision behind it. The posture is jsonl.py's — refuse by name,
never skip silently — so the door can answer typed with the file the
human has to look at.
"""

import json
from pathlib import Path

from engine.contracts.validate import ContractError


def read_json(path: Path) -> dict:
    """The parsed object, or ContractError naming the file."""
    path = Path(path)
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ContractError(
            f"{path}: not a JSON record ({exc.msg} at line {exc.lineno}) "
            "— the record is evidence, stop and see the recovery runbook"
        ) from exc
    if not isinstance(obj, dict):
        raise ContractError(
            f"{path}: a JSON {type(obj).__name__}, not a record object — "
            "the record is evidence, stop and see the recovery runbook")
    return obj
