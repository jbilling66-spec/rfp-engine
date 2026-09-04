"""P0-22 (found in P26c while touching the inbox): the workbench script
must PARSE. A parse-time SyntaxError aborts the whole file in a browser
— app.js shipped with `const dl` declared twice in one function from
P27 wave 1 (pilot-2.3) through pilot-2.5, so the workbench could never
load, and no test noticed: the UI-surface pins read path literals,
never the script. This test parses every static script with a real
JavaScript engine — node where the runner has one (CI), JavaScriptCore
through osascript on macOS — and SKIPS BY NAME where neither exists, so
a green here is a parse, never a silent pass."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[2] / "engine" / "web" / "static"
SCRIPTS = sorted(STATIC.glob("*.js"))


def _engine() -> str | None:
    if shutil.which("node"):
        return "node"
    if sys.platform == "darwin" and shutil.which("osascript"):
        return "osascript"
    return None


def _parse(path: Path) -> subprocess.CompletedProcess:
    if _engine() == "node":
        return subprocess.run(["node", "--check", str(path)],
                              capture_output=True, text=True)
    script = ('ObjC.import("Foundation"); var s = $.NSString.'
              'stringWithContentsOfFileEncodingError(%r, 4, null).js; '
              'new Function(s); "ok"' % str(path))
    return subprocess.run(["osascript", "-l", "JavaScript", "-e", script],
                          capture_output=True, text=True)


def _require_engine():
    if _engine() is None:
        pytest.skip("no JavaScript engine on this runner (node, or "
                    "osascript on macOS) — the parse guard did not run")


@pytest.mark.parametrize("path", SCRIPTS, ids=[p.name for p in SCRIPTS])
def test_every_static_script_parses(path):
    _require_engine()
    result = _parse(path)
    assert result.returncode == 0, (
        f"{path.name} does not parse:\n{result.stderr or result.stdout}")


def test_the_static_scripts_are_present():
    assert {p.name for p in SCRIPTS} >= {"app.js", "share.js"}


def test_the_guard_can_fail(tmp_path):
    _require_engine()
    bad = tmp_path / "bad.js"
    bad.write_text("function f() { const x = 1; const x = 2; }\n",
                   encoding="utf-8")
    assert _parse(bad).returncode != 0
