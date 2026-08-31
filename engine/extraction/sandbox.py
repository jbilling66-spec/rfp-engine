"""Sandboxed execution for document parsers (C2, B51).

Parsers are a classic attack surface and buyer documents are untrusted
input (spec §A3/S1): the parse runs in a child process with no network,
an offline model-hub environment, a memory ceiling (enforced on Linux —
the gate container and A5; best-effort on macOS), a wall-clock timeout,
and cwd jailed to the caller's workdir. A malformed document may kill
the parse and nothing else.

Deliberately a function, not a framework (spec rule 2). The container's
`--network none` is the outer wall; this is the inner one, testable
everywhere without docling installed.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]

_STDERR_TAIL = 800


@dataclass
class SandboxResult:
    status: str  # "ok" | "failed" | "timeout"
    result: dict | None
    error: str | None
    duration_ms: int
    peak_rss_bytes: int | None


def run_sandboxed(
    target: str,
    payload: dict,
    *,
    timeout_s: float,
    mem_mb: int,
    workdir: Path,
) -> SandboxResult:
    """Run `pkg.mod:func` in a jailed child; func(payload) -> dict.

    The child imports code via PYTHONPATH (the repo), not via its cwd —
    the jail governs where the target may write, not what it may import.
    Results travel through a file in the workdir, immune to whatever the
    target's libraries print on stdout.
    """
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    result_name = f"_sandbox_{uuid.uuid4().hex}.json"

    env = {k: v for k, v in os.environ.items() if not k.lower().endswith("_proxy")}
    env.update(
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
        HF_HUB_DISABLE_TELEMETRY="1",
    )
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (str(_REPO_ROOT), env.get("PYTHONPATH", "")) if p
    )

    spec = {"payload": payload, "mem_mb": mem_mb, "result_file": result_name}
    start = time.monotonic()
    proc = subprocess.Popen(
        [sys.executable, "-m", "engine.extraction._child", target],
        cwd=workdir,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        _, err = proc.communicate(json.dumps(spec), timeout=timeout_s)
    except subprocess.TimeoutExpired:
        # The whole process group: a parser's own children die with it.
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()
        duration = int((time.monotonic() - start) * 1000)
        return SandboxResult(
            "timeout", None, f"wall clock exceeded {timeout_s}s", duration, None
        )

    duration = int((time.monotonic() - start) * 1000)
    result_path = workdir / result_name
    if result_path.exists():
        data = json.loads(result_path.read_text(encoding="utf-8"))
        result_path.unlink()  # leave the workdir as the target left it
        if data.get("ok"):
            return SandboxResult(
                "ok", data.get("result"), None, duration, data.get("peak_rss")
            )
        return SandboxResult(
            "failed", None, data.get("error"), duration, data.get("peak_rss")
        )

    tail = (err or "").strip()[-_STDERR_TAIL:]
    return SandboxResult(
        "failed",
        None,
        f"child died without a result (exit {proc.returncode}): {tail}",
        duration,
        None,
    )
