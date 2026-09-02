"""The cross-process workspace lock (P25 item 2; register P0-4).

`serve.lock` was the web server's flock — server-vs-server only. Every
process that MUTATES a workspace now takes the same lock through this
seam: the server for its lifetime, a mutating CLI command (`intake run`,
`slice`, `kb purge`) for the length of the command. A held lock refuses
loudly and immediately (LOCK_NB — never a silent wait), naming the
holder; a dead holder releases through the OS. In-process serialization
(the job lane's per-pursuit guard) stays what it is — this seam is the
boundary BETWEEN processes, which nothing covered before.
"""

import fcntl
import os
from pathlib import Path

LOCK_NAME = "serve.lock"


class WorkspaceLocked(RuntimeError):
    """Another process holds this workspace's lock."""


class WorkspaceLock:
    def __init__(self, workspace: Path):
        self.workspace = Path(workspace)
        self.path = self.workspace / LOCK_NAME
        self._file = None

    def acquire(self, *, holder: str) -> "WorkspaceLock":
        self.workspace.mkdir(parents=True, exist_ok=True)
        handle = open(self.path, "a+")
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.seek(0)
            who = handle.read().strip()
            handle.close()
            raise WorkspaceLocked(
                f"another process already holds {self.path}"
                + (f" ({who})" if who else "")
                + " — one writer per workspace")
        handle.seek(0)
        handle.truncate()
        handle.write(f"{holder} pid {os.getpid()}\n")
        handle.flush()
        self._file = handle
        return self

    @property
    def held(self) -> bool:
        return self._file is not None

    def release(self) -> None:
        if self._file is not None:
            fcntl.flock(self._file, fcntl.LOCK_UN)
            self._file.close()
            self._file = None

    def __enter__(self) -> "WorkspaceLock":
        return self

    def __exit__(self, *exc) -> None:
        self.release()


def workspace_lock(workspace: Path, *, holder: str) -> WorkspaceLock:
    """Acquire now (refuse loudly if held); use as a context manager or
    call `release()` yourself."""
    return WorkspaceLock(workspace).acquire(holder=holder)
