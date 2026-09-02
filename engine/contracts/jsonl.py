"""The one JSONL reader (P26a Group C, P1-17).

Every append-only record in this repo (run logs, the jobs journal, the
events lane, pings, share links) is fsync'd per line but unlocked across
processes, so a reader can catch — or a crash can leave — a half-written
FINAL line. The rule, stated once (it used to live only in the metrics
walker): tolerate a torn final line and nothing else. A torn line
anywhere earlier is corruption, refused by name; a torn tail is reported
to the caller, never skipped silently.
"""

import json
from pathlib import Path

from engine.contracts.validate import ContractError


def read_jsonl(path: Path) -> tuple[list[dict], str | None]:
    """-> (records, torn) — `torn` is None or a short reason naming the
    file and the byte length of the torn final line. A torn line that is
    NOT the last one raises ContractError naming its line number."""
    path = Path(path)
    if not path.exists():
        return [], None
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    records: list[dict] = []
    torn = None
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            if index == len(lines) - 1 and not text.endswith("\n"):
                torn = (f"{path.name}: torn final line "
                        f"({len(line.encode('utf-8'))} bytes) — a writer "
                        "caught mid-append")
                continue
            raise ContractError(
                f"{path}: line {index + 1} is not a JSON record ({exc.msg}) "
                "— this is corruption, not a torn tail; the record is "
                "evidence, stop and see the recovery runbook") from exc
    return records, torn


def torn_tail_offset(path: Path) -> int | None:
    """The byte offset at which a torn final line starts, or None when
    the file ends cleanly — what a repairing writer truncates to."""
    data = Path(path).read_bytes()
    if not data or data.endswith(b"\n"):
        return None
    cut = data.rfind(b"\n")
    return cut + 1 if cut >= 0 else 0
