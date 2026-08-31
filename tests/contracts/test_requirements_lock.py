"""requirements.lock matches the running environment (B30(h), closed at P8).

Named a deliberate cut at B30 "until the live caller makes supply-chain
drift consequential" — it now does (anthropic is pinned and imported by the
live path). Both directions: every pinned distribution is installed at its
pinned version, and nothing is installed beyond the lock except the named
tooling trio (pip/setuptools, which `pip freeze` itself excludes) and the
project's own editable install (`--exclude-editable`). A red here means the
environment and the record disagree — fix the environment or re-run
`make lock` deliberately, never ignore it.
"""

import importlib.metadata
from pathlib import Path

LOCK = Path(__file__).resolve().parents[2] / "requirements.lock"

# pip freeze's own exclusions + the editable project itself.
TOOLING = {"pip", "setuptools", "wheel", "rfp-engine-v2"}


def _norm(name: str) -> str:
    return name.strip().lower().replace("_", "-")


def _lock_pins() -> dict[str, str]:
    pins = {}
    for line in LOCK.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "==" not in line:
            continue
        name, _, version = line.partition("==")
        pins[_norm(name)] = version.strip()
    return pins


def _installed() -> dict[str, str]:
    return {
        _norm(dist.metadata["Name"] or ""): dist.version
        for dist in importlib.metadata.distributions()
    }


def test_lock_is_nonempty_and_pins_the_live_dependency():
    pins = _lock_pins()
    assert len(pins) >= 40
    assert "anthropic" in pins  # the dependency that made drift consequential


def test_every_pin_is_installed_at_its_pinned_version():
    pins, installed = _lock_pins(), _installed()
    missing = sorted(name for name in pins if name not in installed)
    drifted = {
        name: (pinned, installed[name])
        for name, pinned in pins.items()
        if name in installed and installed[name] != pinned
    }
    assert not missing, f"pinned but not installed: {missing}"
    assert not drifted, (
        f"version drift (lock, installed): {drifted} — re-run `make lock` "
        f"deliberately or repair the environment")


def test_nothing_installed_beyond_the_lock():
    extras = sorted(set(_installed()) - set(_lock_pins()) - TOOLING)
    assert not extras, (
        f"installed but not pinned: {extras} — an unpinned package in the "
        f"live path is supply-chain drift; add it via `make lock` or remove it")
