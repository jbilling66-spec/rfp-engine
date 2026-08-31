"""Append-only JSONL run logger — built first so every later stage is traced
by construction (WP0), not instrumented after the fact.

One RunLogger per run. `seq` is a monotonic counter under a lock; ordering
is by seq, never ts — parallel drafters share wall-clock and their
timestamps lie about order. Every line is schema-validated and
payload-checked (B10) before it is written; a record that would corrupt the
trace raises instead of landing. No raw client text enters a line: prompts
and tool arguments pass through digest().
"""

import hashlib
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

from engine.contracts import ContractError, check_runlog_payloads, validate


def digest(text: str) -> str:
    """Short stable digest for text that must not appear in a log line."""
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def config_digest(config: dict) -> str:
    """Digest of the effective run config. Same digest = comparable runs (O4)."""
    canonical = json.dumps(config, sort_keys=True, separators=(",", ":"))
    return "cfg:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def read_run(run_jsonl: Path) -> list[dict]:
    """Read a run.jsonl back into records (already seq-ordered on disk)."""
    lines = run_jsonl.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


class RunLogger:
    """Writer for <pursuit>/runs/<run_id>/run.jsonl.

    Resume-safe: opening a logger on an existing run.jsonl continues seq
    from the last line rather than restarting at 0 (N2 — a resumed run is
    the same run).
    """

    def __init__(self, pursuit_dir: Path, run_id: str, pursuit_id: str):
        self.run_id = run_id
        self.pursuit_id = pursuit_id
        self.run_dir = Path(pursuit_dir) / "runs" / run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.run_dir / "run.jsonl"
        self._lock = threading.Lock()
        self._seq = 0
        self._totals = {
            "cost_usd": 0.0,
            "input_tokens": 0,
            "output_tokens": 0,
            "agent_calls": 0,
            "gaps_opened": 0,
            "tier1_blocks": 0,
            # O6's split, sourced from the lines rather than asserted by a
            # caller: compute_ms sums agent_call durations, human_wait_ms
            # sums the gate waits, and wall_ms is the run's own span. All
            # three were schema-declared with no writer, which left
            # cycle_time_days and compute_vs_human_wait dormant.
            "compute_ms": 0,
            "human_wait_ms": 0,
        }
        self._first_ts: str | None = None
        self._last_ts: str | None = None
        if self.path.exists():
            records = read_run(self.path)
            if records:
                self._seq = records[-1]["seq"] + 1
                self._replay_totals(records)

    def _replay_totals(self, records: list[dict]) -> None:
        for rec in records:
            self._accumulate(rec)

    def _accumulate(self, rec: dict) -> None:
        ts = rec.get("ts")
        if ts:
            if self._first_ts is None:
                self._first_ts = ts
            self._last_ts = ts
        if rec["record_type"] == "agent_call":
            self._totals["agent_calls"] += 1
            self._totals["cost_usd"] = round(
                self._totals["cost_usd"] + rec.get("cost_usd", 0.0), 6
            )
            self._totals["compute_ms"] += rec.get("duration_ms", 0)
            tokens = rec.get("tokens", {})
            self._totals["input_tokens"] += tokens.get("input", 0)
            self._totals["output_tokens"] += tokens.get("output", 0)
        elif rec["record_type"] == "gate":
            self._totals["human_wait_ms"] += rec.get("gate", {}).get(
                "wait_ms", 0)
        elif rec["record_type"] == "gap":
            self._totals["gaps_opened"] += 1
        elif rec["record_type"] == "validation":
            if rec.get("validation", {}).get("result") == "block":
                self._totals["tier1_blocks"] += 1

    def emit(self, record_type: str, **fields) -> int:
        """Validate and append one line; returns its seq. Raises on contract
        violations — a bad record never lands."""
        with self._lock:
            record = {
                "run_id": self.run_id,
                "pursuit_id": self.pursuit_id,
                "seq": self._seq,
                "ts": _now(),
                "record_type": record_type,
                **fields,
            }
            validate("run_log", record)
            check_runlog_payloads(record)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, separators=(",", ":")) + "\n")
                f.flush()
                os.fsync(f.fileno())
            self._seq += 1
            self._accumulate(record)
            return record["seq"]

    def run_start(self, *, mode: str, engine_version: str, config: dict,
                  kb_snapshot: str, **run_fields) -> int:
        """Open the run: persist the effective config beside the log and emit
        the header carrying its digest (O4)."""
        config_path = self.run_dir / "config.json"
        config_path.write_text(
            json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return self.emit(
            "run_start",
            run={
                "mode": mode,
                "engine_version": engine_version,
                "config_digest": config_digest(config),
                "kb_snapshot": kb_snapshot,
                **run_fields,
            },
        )

    def run_end(self, *, status: str, **totals_extra) -> int:
        """Close the run with the totals rollup, reconciled from what was
        actually emitted — the footer cannot disagree with the lines."""
        totals = {**self._totals, **totals_extra}
        if "wall_ms" not in totals:
            totals["wall_ms"] = self._wall_ms()
        return self.emit("run_end", run={"status": status, "totals": totals})

    def _wall_ms(self) -> int:
        """The run's own span, first line to last. Wall clock is honest
        here in a way it is not inside a stage: this is elapsed calendar
        time, which is exactly what cycle-time reporting asks for, and it
        is derived from timestamps already on the record rather than a
        second clock that could disagree with them."""
        if not self._first_ts or not self._last_ts:
            return 0
        start = datetime.fromisoformat(self._first_ts.replace("Z", "+00:00"))
        end = datetime.fromisoformat(self._last_ts.replace("Z", "+00:00"))
        return max(0, int((end - start).total_seconds() * 1000))


def assert_seq_gapless(records: list[dict]) -> None:
    """A trace with a seq gap lost a line; fail loudly (used by tests and
    the resume path)."""
    seqs = [r["seq"] for r in records]
    if seqs != list(range(len(seqs))):
        raise ContractError(f"run log seq is not gapless: {seqs}")
