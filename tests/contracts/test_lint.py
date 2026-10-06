"""P32d (P1-10's ruff half, B149): ruff runs inside the suite over the three
source trees with the configuration in pyproject.toml — no make target of its
own, so `make check` and CI are exactly what they were. A red here is a
finding to fix, or a rule to ignore DELIBERATELY in pyproject with its count
and its trigger — never a weakened assertion. The configuration is pinned so
that moving it is a reviewed change (the bar-pin precedent, B148 §4h)."""

import subprocess
import sys
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TREES = ("engine", "tests", "tools")


def _config() -> dict:
    with (REPO / "pyproject.toml").open("rb") as fh:
        return tomllib.load(fh)["tool"]["ruff"]


def test_ruff_is_clean_over_the_three_source_trees():
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--no-cache", *TREES],
        cwd=REPO, capture_output=True, text=True, check=False)
    assert proc.returncode == 0, (
        "ruff findings — fix them, or ignore the rule deliberately in "
        "pyproject.toml with its count and trigger:\n"
        + proc.stdout + proc.stderr)


def test_the_configuration_is_the_recorded_one():
    cfg = _config()
    assert cfg["target-version"] == "py311"
    lint = cfg["lint"]
    assert lint["select"] == ["E", "F", "B", "BLE", "RUF100"]
    # B149 §3c: four rules ignored at adoption, each with its count and its
    # trigger beside it in pyproject; adding or dropping one is deliberate
    assert lint["ignore"] == ["E501", "E741", "B904", "B905"]
    assert lint["per-file-ignores"] == {"__init__.py": ["F401"]}
    # the lint runs cache-free, so no tree (the repo, the public cut's
    # staging) gains a .ruff_cache/ from the suite; hand runs are ignored
    gitignore = (REPO / ".gitignore").read_text(encoding="utf-8").split()
    assert ".ruff_cache/" in gitignore
