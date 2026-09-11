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

from engine.contracts.validate import ContractError


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


def archive_aside(path: Path) -> Path:
    """Move an unreadable DERIVED record out of the way — renamed to
    `<name>.corrupt-<NNN>` beside it by `os.replace`, nothing destroyed
    — so the stage that owns it can rebuild it (P2-62, P29b b4). Only a
    record bound to its inputs by hash and rebuilt from them qualifies
    (the annotated draft); an append-only record is evidence and stops
    (`jsonl.py`), and an artifact carrying human work is never archived
    by the engine (the draft: a typed refusal names the runbook)."""
    path = Path(path)
    n = len(list(path.parent.glob(f"{path.name}.corrupt-*"))) + 1
    dest = path.parent / f"{path.name}.corrupt-{n:03d}"
    os.replace(path, dest)
    return dest


def _unterminated_tail(path: Path) -> bytes | None:
    """The bytes after the last newline when the file does not end in
    one — None for a missing, empty, or cleanly terminated file. Read
    from the end in growing chunks, never the whole file."""
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        return None
    if size == 0:
        return None
    chunk = 4096
    with open(path, "rb") as f:
        while True:
            start = max(0, size - chunk)
            f.seek(start)
            buf = f.read(size - start)
            if buf.endswith(b"\n"):
                return None
            cut = buf.rfind(b"\n")
            if cut >= 0:
                return buf[cut + 1:]
            if start == 0:
                return buf
            chunk *= 4


def append_fsync(path: Path, line: str, *,
                 repair_torn: bool = False) -> tuple[str, str] | None:
    """Append one record line (a trailing newline is added when absent),
    flushed and fsync'd before returning — the journal/transcript rule
    every append-only record follows (the run log, the jobs journal,
    the events, share and pings lanes, the curation log, transcripts).

    P29b (P1-51, P3-20): the ONE tail rule, checked once before every
    append. A complete final record that lost its newline (a crash after
    the bytes, before the terminator) gets the newline written FIRST, in
    the same handle, and is never called torn — a reader parses it, and
    truncating it would destroy a good record. A torn final line (one
    that does not parse) is never appended onto — the fused line is the
    corruption every later read refuses by name — so the append raises
    unless the caller, holding its lane's lock, asks for `repair_torn`,
    in which case the fragment is truncated (fsync'd) before the line
    lands. Returns None for a clean tail, else `(code, reason)` —
    `tail_newline_repaired` or `torn_tail_truncated`, the bytes named —
    for the caller to record.
    """
    path = Path(path)
    if not line.endswith("\n"):
        line += "\n"
    repaired = None
    tail = _unterminated_tail(path)
    if tail is not None:
        try:
            json.loads(tail.decode("utf-8"))
            complete = True
        except (ValueError, UnicodeDecodeError):
            complete = False
        if complete:
            line = "\n" + line
            repaired = ("tail_newline_repaired",
                        f"{path.name}: the final record lacked its newline "
                        "— written before this append")
        elif not repair_torn:
            raise ContractError(
                f"{path}: torn final line ({len(tail)} bytes) — a writer "
                "caught mid-append; the lane repairs it under its own lock "
                "before appending, never by concatenation")
        else:
            size = path.stat().st_size
            with open(path, "r+b") as f:
                f.truncate(size - len(tail))
                f.flush()
                os.fsync(f.fileno())
            repaired = ("torn_tail_truncated",
                        f"{path.name}: {len(tail)} bytes of a torn final "
                        "line dropped before this append")
    with open(path, "a", encoding="utf-8") as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())
    return repaired
