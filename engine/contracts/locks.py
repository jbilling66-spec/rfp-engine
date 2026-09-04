"""In-process mutual exclusion keyed by path (P26b-2, P1-40).

The firm KB had none: `merge_batch` was check-then-act per proposal and
the KB routes built a fresh store per request on the server's thread
pool, so two stewards could interleave and both curation-log snapshot
pairs lied. `WorkspaceLock` (an fcntl flock on serve.lock) serializes
PROCESSES; this registry serializes the threads inside one. The same
division `engine/web/events.py`'s append lock states: one process here;
across processes, the workspace flock.

One re-entrant lock per RESOLVED path, so every layer that touches a KB
root — curation, the proposal store, the xlsx import, the client purge,
the accept-time learner — takes the identical object without importing
each other (`contracts` is imported by all of them; the graph gains no
edge). Re-entrant because `merge_batch` decides through the proposal
store, which locks the same root.

Ordering rule, so the two guards never deadlock: the pursuit guard
(`server.py` `_mutate`) is taken OUTSIDE the KB lock, never the reverse.
"""

import threading
from pathlib import Path

_REGISTRY_LOCK = threading.Lock()
_LOCKS: dict[Path, threading.RLock] = {}


def _key(path) -> Path:
    return Path(path).resolve()  # non-strict: a root not yet created keys too


def path_lock(path) -> threading.RLock:
    """The one lock for this path in this process."""
    key = _key(path)
    with _REGISTRY_LOCK:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = _LOCKS[key] = threading.RLock()
        return lock
