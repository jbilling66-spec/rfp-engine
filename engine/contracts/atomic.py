"""The one atomic-write primitive (P26a Group B, P0-6).

Every durable record in this repo is written the same way: bytes into a
temp file in the target's own directory, flushed and fsync'd, then
`os.replace`d over the target — a crash leaves the OLD file intact or
the NEW file complete, never a torn one — and every append-only record
is flushed and fsync'd per line. This module is the single home; the
copies that grew in `workspace`, `kb/store`, and `kb/provenance` now
import it, and `llm/handoff.py` keeps its documented twin (an llm ->
contracts edge is fine, but B81 D2's reasoning about the graph stands
and a contract test pins the twin's load-bearing lines equal to these).
It lives in `contracts` because contracts is the universal leaf: the
durability of a record is part of its contract, and every package that
writes one already imports here.
"""

import json
import os
import tempfile
from pathlib import Path


def write_bytes_atomic(path: Path, data: bytes) -> None:
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def write_text_atomic(path: Path, text: str) -> None:
    write_bytes_atomic(path, text.encode("utf-8"))


def write_json_atomic(path: Path, obj, *, indent: int = 2) -> None:
    """`json.dumps(obj, indent=indent, sort_keys=True) + "\\n"` — the
    repo's record shape (indent 2 for workspace/config records, 1 for
    the eval reports and proposals that already use it)."""
    write_text_atomic(path, json.dumps(obj, indent=indent, sort_keys=True)
                      + "\n")


def append_fsync(path: Path, line: str) -> None:
    """Append one record line (a trailing newline is added when absent),
    flushed and fsync'd before returning — the journal/transcript rule
    `runlog/writer.py` and the events lane already follow."""
    path = Path(path)
    if not line.endswith("\n"):
        line += "\n"
    with open(path, "a", encoding="utf-8") as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())
