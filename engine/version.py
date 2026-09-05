"""engine_version resolves to a commit (N3) — a release is a commit, and a
run log naming one is reproducible. Falls back to the bare version when git
is unavailable (e.g. a deployed image without .git)."""

import subprocess
from pathlib import Path

VERSION = "0.8.0"
_ROOT = Path(__file__).resolve().parents[1]


def engine_version() -> str:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=_ROOT, capture_output=True, text=True, check=True,
        ).stdout.strip()
        return f"{VERSION}+{commit}"
    except (subprocess.CalledProcessError, FileNotFoundError):
        return VERSION
