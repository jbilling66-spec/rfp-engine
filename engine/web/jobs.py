"""The job runner (B37/D2): ONE global worker thread, FIFO queue —
single-worker IS the P9 concurrency decision (G15), and it is what makes
`PursuitDir.new_run_id()`'s directory-listing mint safe: every run-
creating execution is serialized here, and mutating routes serialize
against a running job through the same per-pursuit lock (`guard`).

One job per pursuit: a second submission while one runs is a 409, never
a queue-behind — the caller should see the truth, not a silent backlog.
(v1's lock; v1 never tested its 409 — tests/web does.)

Journal: append-only `<workspace>/jobs.jsonl`, one line at start and one
at finish (last line per id wins). Boot rehydration replays it and flips
any `running` line from a dead server to `orphaned` — a badge that said
"running" forever would lie. Deleting a pursuit never rewrites history.

Error lanes are TYPED (v1 keeper): ContractError -> `refused` (a rule
said no), CostCeilingExceeded -> `refused` naming the ceiling,
OutputTruncated/LiveCallError -> `refused` (live-transport refusals are
refusals), HandoffTimeout -> `refused` (an unanswered handoff is an
absent operator, not a bug — P20/B81 D8), anything else -> `error` with
the exception class named. `refused` is not `error`: one is the system
working, the other is a bug.

Cancel is cooperative and only for kinds whose target polls the flag —
a `cancelled` badge on work that ran to completion would lie. No P9 c8
kind polls yet (the pipeline stages checkpoint per-section but take no
cancel hook); the revise job becomes the first cancellable kind.
"""

import itertools
import json
import queue
import threading
from collections import defaultdict
from pathlib import Path

from engine.contracts import ContractError
from engine.llm.caller import CostCeilingExceeded
from engine.llm.handoff import HandoffTimeout
from engine.llm.live import LiveCallError

# Only kinds whose target actually polls the flag — a cancelled badge on
# work that ran to completion would lie. revise polls between sections.
CANCELLABLE_KINDS: frozenset[str] = frozenset({"revise"})

_STATES = ("queued", "running", "done", "refused", "error", "cancelled",
           "orphaned")


class JobRunner:
    def __init__(self, workspace: Path):
        self.workspace = Path(workspace)
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.journal_path = self.workspace / "jobs.jsonl"
        self._jobs: dict[str, dict] = {}
        self._registry_lock = threading.Lock()
        self._pursuit_locks: dict[str, threading.Lock] = defaultdict(
            threading.Lock)
        self._queue: queue.Queue = queue.Queue()
        self._ids = itertools.count(1)
        self._rehydrate()
        self._worker = threading.Thread(target=self._work, daemon=True)
        self._worker.start()

    # -- journal -----------------------------------------------------------

    def _journal(self, job: dict) -> None:
        line = {k: job[k] for k in ("id", "kind", "pursuit", "by", "state",
                                    "message", "at") if k in job}
        with open(self.journal_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(line, sort_keys=True) + "\n")

    def _rehydrate(self) -> None:
        if not self.journal_path.exists():
            return
        last: dict[str, dict] = {}
        for raw in self.journal_path.read_text(encoding="utf-8").splitlines():
            line = json.loads(raw)
            last[line["id"]] = line
        highest = 0
        for job in last.values():
            highest = max(highest, int(job["id"].split("-")[1]))
            if job["state"] in ("running", "queued"):
                job["state"] = "orphaned"
                job["message"] = ("server restarted mid-run — "
                                  + job.get("message", ""))
                self._journal(job)
            self._jobs[job["id"]] = job
        self._ids = itertools.count(highest + 1)

    # -- the per-pursuit serialization point -------------------------------

    def guard(self, pursuit_id: str):
        """The lock every mutating route takes before touching a pursuit
        (and inside which `busy` must be consulted): serializes run-id
        minting between request threads and the job lane."""
        return self._pursuit_locks[pursuit_id]

    def busy(self, pursuit_id: str) -> dict | None:
        for job in self._jobs.values():
            if (job["pursuit"] == pursuit_id
                    and job["state"] in ("queued", "running")):
                return job
        return None

    # -- submission --------------------------------------------------------

    def submit(self, *, kind: str, pursuit_id: str, by: str, at: str,
               target) -> dict:
        """target: callable(job) -> (state, message). Raise-to-lane
        mapping happens here, not in targets. Registry lock ONLY — the
        pursuit guard is held by the worker for a job's whole execution,
        so taking it here would block a submission behind the running
        job instead of 409ing it (the lock is for check+insert, never
        across a run — v1's discipline)."""
        with self._registry_lock:
            running = self.busy(pursuit_id)
            if running is not None:
                raise JobConflict(
                    f"{running['kind']} already "
                    f"{running['state']} for {pursuit_id} "
                    f"(job {running['id']}) — one job per pursuit")
            job = {"id": f"job-{next(self._ids):04d}", "kind": kind,
                   "pursuit": pursuit_id, "by": by, "at": at,
                   "state": "queued", "message": "queued"}
            self._jobs[job["id"]] = job
            self._journal(job)
        self._queue.put((job, target))
        return dict(job)

    # -- the worker --------------------------------------------------------

    def _work(self) -> None:
        while True:
            job, target = self._queue.get()
            if job.get("cancel") and job["state"] == "queued":
                self._finish(job, "cancelled", "cancelled before start")
                continue
            job["state"] = "running"
            job["message"] = "running"
            self._journal(job)
            with self.guard(job["pursuit"]):
                try:
                    state, message = target(job)
                except ContractError as exc:
                    state, message = "refused", str(exc)
                except CostCeilingExceeded as exc:
                    state, message = "refused", (
                        f"{exc} — raise the ceiling deliberately and re-run; "
                        "the brake never silently truncates")
                except LiveCallError as exc:
                    state, message = "refused", str(exc)
                except HandoffTimeout as exc:
                    state, message = "refused", (
                        f"{exc} — an absent operator is a refusal, "
                        "not a bug")
                except Exception as exc:  # noqa: BLE001 — the error lane
                    state, message = "error", f"{type(exc).__name__}: {exc}"
            if (job.get("cancel") and state == "done"
                    and str(message).startswith("cancelled")):
                state = "cancelled"  # the badge follows the flow's report
            self._finish(job, state, message)

    def _finish(self, job: dict, state: str, message: str) -> None:
        assert state in _STATES
        job["state"] = state
        job["message"] = message
        self._journal(job)

    # -- polling / cancel --------------------------------------------------

    def jobs(self, limit: int = 40) -> list[dict]:
        out = sorted(self._jobs.values(), key=lambda j: j["id"], reverse=True)
        return [dict(j) for j in out[:limit]]

    def job(self, job_id: str) -> dict | None:
        job = self._jobs.get(job_id)
        return dict(job) if job else None

    def cancel(self, job_id: str, by: str) -> dict:
        job = self._jobs.get(job_id)
        if job is None:
            raise JobNotFound(f"unknown job {job_id!r}")
        if job["state"] not in ("queued", "running"):
            raise JobConflict(f"job {job_id} already {job['state']}")
        if job["state"] == "running" and job["kind"] not in CANCELLABLE_KINDS:
            raise JobConflict(
                f"{job['kind']} does not poll the cancel flag mid-run — a "
                "cancelled badge on completed work would lie")
        job["cancel"] = True
        job["message"] = f"cancel requested by {by}"
        return dict(job)


class JobConflict(Exception):
    """409-shaped: the lane is busy or the instruction conflicts."""


class JobNotFound(Exception):
    """404-shaped."""
