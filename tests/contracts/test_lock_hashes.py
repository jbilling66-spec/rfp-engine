"""P0-12 (P26a Group E): every pin in requirements.lock carries at least one
sha256 hash, so the documented bootstrap's --require-hashes has something
to require; and the bootstrap lines in CI, the README and the runbook are
the same two lines."""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LOCK = REPO / "requirements.lock"
BOOTSTRAP = ("uv pip install --require-hashes -r requirements.lock",
             "uv pip install --no-deps -e .")


def _pins_with_hashes():
    pins, current, hashed = [], None, set()
    for line in LOCK.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        m = re.match(r"^([A-Za-z0-9_.\-]+)==", stripped)
        if m:
            current = m.group(1).lower()
            pins.append(current)
        if "--hash=sha256:" in stripped and current:
            hashed.add(current)
    return pins, hashed


def test_every_pin_carries_a_hash():
    pins, hashed = _pins_with_hashes()
    assert len(pins) >= 40
    assert set(pins) <= hashed, sorted(set(pins) - hashed)


def test_the_documented_bootstrap_is_the_hashed_one_everywhere():
    for doc in ("README.md", "docs/pilot/runbook.md",
                ".github/workflows/check.yml"):
        text = (REPO / doc).read_text(encoding="utf-8")
        for line in BOOTSTRAP:
            assert line in text, (doc, line)
        assert "uv pip install -r requirements.lock -e ." not in text, doc
