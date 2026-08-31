"""Where the restricted-token list lives (B85 D3): a machine-local file.

The tripwire scans were born with their token list in a tracked file — the
correct design for a private repo, and a disclosure the moment the repo has
any other audience. From B85 the list is data, not code:

  * ``tripwire-local/tokens.txt`` (gitignored) carries the REAL tokens, one
    per line, ``#`` comments allowed. It is machine state, restored at
    bootstrap like the venv. Missing or empty -> the suite fails loudly;
    a lost list must never look like a clean one.
  * ``tests/tripwire/ATTESTATION.md`` (committed only in the public mirror,
    never here) is the one way to run with an empty list: an explicit,
    reviewable statement that this checkout has no restricted names yet.
    A local tokens.txt always overrides it.
  * ``tests/tripwire/probe-sentinel.txt`` (committed) carries one clearly
    synthetic token that every scan appends to its list, so every scan's
    ability to FAIL is proven on real plumbing — including on a fresh
    single-commit history where no real token has ever existed.

Per the paraphrase law (CLAUDE.md standing rules), nothing in this module
names a real token; the local file carries its own provenance comments.
"""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TOKENS_FILE = REPO_ROOT / "tripwire-local" / "tokens.txt"
ATTESTATION_FILE = REPO_ROOT / "tests" / "tripwire" / "ATTESTATION.md"
PROBE_FILE = REPO_ROOT / "tests" / "tripwire" / "probe-sentinel.txt"

# Repo-relative path form, for offender-exclusion sets in the scans.
PROBE_PATH = "tests/tripwire/probe-sentinel.txt"

# The attestation is only honored when it says exactly this — an empty or
# unrelated file must not silence the tripwire.
ATTESTATION_SENTENCE = (
    "This repository runs the tripwire with no restricted-token list: "
    "we accept that only the synthetic probe is scanned for, and we will "
    "create tripwire-local/tokens.txt before any restricted name exists."
)


def norm_ws(text: str) -> str:
    """Presentation fold for prose checks: line wraps must not break a
    sentence match (the P21 blockquote lesson, B84 §2a)."""
    return " ".join(text.split())


def _parse(text: str) -> list[str]:
    tokens = []
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            tokens.append(line.lower())
    return tokens


def probe_token() -> str:
    """The committed synthetic sentinel. Blank or missing is a broken
    tripwire, never a pass."""
    if not PROBE_FILE.exists():
        pytest.fail(
            f"{PROBE_PATH} is missing — the scans' non-vacuity probe is "
            "gone, so no scan can prove it is able to fail"
        )
    tokens = _parse(PROBE_FILE.read_text(encoding="utf-8"))
    if len(tokens) != 1:
        pytest.fail(
            f"{PROBE_PATH} must carry exactly one synthetic probe token "
            f"(found {len(tokens)}) — a blank probe makes every scan's "
            "non-vacuity check meaningless"
        )
    return tokens[0]


def client_tokens() -> list[str]:
    """The REAL restricted tokens, or [] only under the explicit committed
    attestation. Never silently empty (B85 D3)."""
    if TOKENS_FILE.exists():
        tokens = _parse(TOKENS_FILE.read_text(encoding="utf-8"))
        if not tokens:
            pytest.fail(
                "tripwire-local/tokens.txt exists but lists no tokens — "
                "an empty list is a decision, not a default: either name "
                "the restricted tokens or delete the file and commit "
                "tests/tripwire/ATTESTATION.md accepting the empty-list "
                "posture"
            )
        return tokens
    if ATTESTATION_FILE.exists():
        if norm_ws(ATTESTATION_SENTENCE) not in norm_ws(
            ATTESTATION_FILE.read_text(encoding="utf-8")
        ):
            pytest.fail(
                "tests/tripwire/ATTESTATION.md exists but does not carry "
                "the required attestation sentence — it cannot silence the "
                "tripwire by accident"
            )
        return []
    pytest.fail(
        "no restricted-token list: create tripwire-local/tokens.txt (one "
        "token per line, # comments allowed) naming YOUR organization's "
        "restricted client/firm names, or commit tests/tripwire/"
        "ATTESTATION.md explicitly accepting the empty-list posture. The "
        "tripwire refuses to guess (B85 D3)."
    )


def scan_tokens() -> list[str]:
    """What every scan actually sweeps for: the real list plus the probe.
    Never empty, so scan plumbing is always exercised."""
    return client_tokens() + [probe_token()]
