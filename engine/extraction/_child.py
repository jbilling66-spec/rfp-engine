"""Sandbox child bootstrap (C2, B51). Run only via engine.extraction.sandbox.

Order matters: the memory ceiling and network denial are applied BEFORE
the target module is imported, so a parser's import-time behavior is
already jailed. This module itself imports nothing beyond the stdlib.
"""

from __future__ import annotations

import importlib
import json
import os
import sys


class SandboxNetworkDenied(OSError):
    pass


def _deny_network() -> None:
    # Connect-level denial: TCP egress and DNS both die here; local
    # socketpair plumbing some libraries use internally stays alive.
    import socket

    def _denied(*_a, **_k):
        raise SandboxNetworkDenied(
            "network access is denied inside the parse sandbox (B51)"
        )

    socket.socket.connect = _denied
    socket.socket.connect_ex = _denied
    socket.create_connection = _denied
    socket.getaddrinfo = _denied


def _apply_memory_ceiling(mem_mb: int) -> bool:
    import resource

    limit = mem_mb * 1024 * 1024
    try:
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
        return True
    except (ValueError, OSError):
        return False  # macOS best-effort; the gate container enforces


def _peak_rss_bytes() -> int:
    import resource

    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return rss if sys.platform == "darwin" else rss * 1024


def main() -> int:
    target = sys.argv[1]
    spec = json.load(sys.stdin)
    result_file = spec["result_file"]

    os.environ.update(
        HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1"
    )
    ceiling_applied = _apply_memory_ceiling(spec["mem_mb"])
    _deny_network()

    record: dict
    try:
        mod_name, func_name = target.split(":")
        func = getattr(importlib.import_module(mod_name), func_name)
        result = func(spec["payload"])
        record = {"ok": True, "result": result}
    except BaseException as exc:  # a jailed parser may die any way it likes
        record = {"ok": False, "error": f"{exc.__class__.__name__}: {exc}"}
    record["peak_rss"] = _peak_rss_bytes()
    record["mem_ceiling_applied"] = ceiling_applied

    with open(result_file, "w", encoding="utf-8") as fh:
        json.dump(record, fh)
    return 0 if record["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
