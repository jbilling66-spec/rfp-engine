"""The cross-pursuit record walker the resolver reads through.

Nothing like this existed: slice.py's _all_records is private and
single-pursuit, state.board is web-shaped, and pings has its own
cross-pursuit reader. The resolver needs one honest pass over every
pursuit's run logs, feedback events, and pings.

Three disciplines, each answering a real trap:

* Never CONSTRUCT a PursuitDir to read (its __init__ mkdirs, so a read
  would create the phantom pursuit it came to look at — v1 trap 1, the
  same guard server.py:_pursuit_root uses).
* Tolerate a torn FINAL line and nothing else. Appends are fsync'd but
  unlocked across processes, so a resolver running beside `engine serve`
  can catch a half-written last line; skipping it is honest, while
  skipping anywhere else would silently drop records.
* Read-only, always. The resolver never mints a run id, so the
  new_run_id TOCTOU cannot bite it.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

from engine.contracts import read_jsonl


@dataclass
class PursuitRecords:
    pursuit_id: str
    root: Path
    runs: list[dict] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    pings: list[dict] = field(default_factory=list)
    torn_lines: list[str] = field(default_factory=list)


def _read_jsonl(path: Path, torn: list[str]) -> list[dict]:
    # P26a Group C: the tolerant read lives in engine/contracts/jsonl.py
    # (one rule, one home); this keeps the walker's torn-lines report.
    records, reason = read_jsonl(path)
    if reason is not None:
        torn.append(f"{path}: {reason}")
    return records


def is_pursuit_dir(root: Path) -> bool:
    """The same predicate the board uses: kb/, support/ and other
    workspace neighbours are not pursuits."""
    return root.is_dir() and ((root / "brief.json").exists()
                              or (root / "inbox").exists())


def read_pursuit(root: Path) -> PursuitRecords:
    root = Path(root)
    torn: list[str] = []
    runs: list[dict] = []
    runs_dir = root / "runs"
    if runs_dir.is_dir():
        for run_dir in sorted(p for p in runs_dir.iterdir() if p.is_dir()):
            runs.extend(_read_jsonl(run_dir / "run.jsonl", torn))
    return PursuitRecords(
        pursuit_id=root.name,
        root=root,
        runs=runs,
        events=_read_jsonl(root / "events" / "events.jsonl", torn),
        pings=_read_jsonl(root / "pings" / "pings.jsonl", torn),
        torn_lines=torn,
    )


def walk(workspace: Path) -> list[PursuitRecords]:
    """Every pursuit in a workspace, in id order. An absent workspace is
    an empty walk, not an error — a resolver asked about a workspace
    nobody has used yet should say "no data", not raise."""
    workspace = Path(workspace)
    if not workspace.exists():
        return []
    return [read_pursuit(root)
            for root in sorted(p for p in workspace.iterdir()
                               if is_pursuit_dir(p))]


def run_headers(records: list[dict]) -> dict[str, dict]:
    """run_id -> the run_start payload, so a caller can filter records by
    the mode of the run that produced them. O3's exclusion rule needs
    this join: mode lives on the header, not on every line."""
    # P1-32: a run id is unique only WITHIN a pursuit (each mints its own
    # run_0001); across the flattened corpus the key is the pair
    return {(r.get("pursuit_id"), r["run_id"]): r["run"]
            for r in records if r.get("record_type") == "run_start"}


def production_only(records: list[dict],
                    excluded_modes=("replay", "regression_bench", "dry_run"),
                    ) -> list[dict]:
    """Drop every record belonging to a non-production run (O3).

    A record whose run has no header is dropped too: an unattributable
    line cannot be proven to be production, and counting it would let a
    bench run leak into a production series through a missing header —
    exactly the failure the rule exists to prevent."""
    headers = run_headers(records)
    keep = {key for key, header in headers.items()
            if header.get("mode") not in excluded_modes}
    return [r for r in records
            if (r.get("pursuit_id"), r.get("run_id")) in keep]
