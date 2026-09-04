"""engine/contracts/locks.py (P26b-2, P1-40): one re-entrant lock per
resolved path, process-wide, shared by every layer that names the path."""

import threading
from pathlib import Path

from engine.contracts import path_lock


def test_same_path_same_lock_different_path_different(tmp_path):
    a = path_lock(tmp_path / "kb")
    assert path_lock(tmp_path / "kb") is a
    assert path_lock(tmp_path / "other" / ".." / "kb") is a, \
        "keyed by the RESOLVED path, not the spelling"
    assert path_lock(str(tmp_path / "kb")) is a
    assert path_lock(tmp_path / "kb2") is not a


def test_the_lock_is_reentrant(tmp_path):
    lock = path_lock(tmp_path / "kb")
    with lock:
        with lock:  # a nested take from the same thread does not deadlock
            assert isinstance(lock, type(threading.RLock()))


def test_a_root_that_does_not_exist_yet_still_keys(tmp_path):
    missing = tmp_path / "never" / "created"
    assert not missing.exists()
    assert path_lock(missing) is path_lock(missing)
