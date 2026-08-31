"""The synthetic-data boundary, extended backwards through git history
(recorded decision B45, 2026-08-10).

`test_client_tokens.py` scans the WORKING TREE: every file `git ls-files`
reports at HEAD. That is the right guard for "what does this repo contain",
and it is blind to one thing — a token committed in an earlier commit and
deleted later. The tree would be clean while the history still carried it,
and history is what gets cloned, mirrored, and pushed to a remote.

Two tracks, matching the working-tree tripwire exactly rather than inventing
a second discipline:

  * TEXT blobs are scanned raw, across every commit reachable from any ref.
  * OPAQUE blobs are scanned through the REAL extractor, never raw bytes.

That second rule is load-bearing and was learned here. A raw scan of an
xlsx hits the boilerplate Office theme every openpyxl workbook ships: 58
`<a:font script="…" typeface="…"/>` mappings, one of whose TYPEFACE names
contains a tripwire token as a substring. Scanning what the extractor
actually surfaces (cell values, hidden segments) is both the honest
question and the one without false positives, and it means this test and
the GOLDENS sweeps cannot disagree about what a binary "contains".

This docstring paraphrases rather than quoting that entry on purpose: the
control's whole shape is "the tokens live in NO tracked file" (B85 — before
that, exactly one), and illustrating a false positive by reproducing a
token would break the control in the file that enforces it. That is not
hypothetical — it is what B47 records happening.

Commit messages and author identity are scanned too: they are history that
no tree scan ever sees.
"""

import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from tests.tripwire.test_client_tokens import _OPAQUE_SUFFIXES
from tests.tripwire.tokens import PROBE_PATH, probe_token, scan_tokens

REPO_ROOT = Path(__file__).resolve().parents[2]

# The file that carried the tokens from the first commit until B85
# externalized the list. Its OLD blobs still name them in this repo's
# history, so the exclusion is permanent here — a fresh-history mirror
# simply never matches it. Matched by PATH, because the blob changed
# whenever the list grew.
_TOKEN_HOME = "tests/tripwire/test_client_tokens.py"

# Paths whose historical blobs legitimately carry a scanned token: the old
# token home, and the committed probe file (whose whole job is to be found).
_EXCLUDED_HOMES = {_TOKEN_HOME, PROBE_PATH}

# The SYNTHETIC buyer every committed twin names. Used only to prove the
# binary scan is reading real extracted content — if this disappears, the
# opaque track is passing on empty strings.
_SYNTHETIC_PROBE = "northwind"


def _git(*args: str, check: bool = True) -> str:
    binary = shutil.which("git")
    if binary is None or not (REPO_ROOT / ".git").exists():
        pytest.fail(
            "history tripwire requires a git checkout: no git binary or no "
            ".git dir — refusing to pass vacuously (CLAUDE.md rule 1 would "
            "be unenforced for everything already committed)"
        )
    result = subprocess.run(
        [binary, *args], cwd=REPO_ROOT, capture_output=True, text=True
    )
    if check and result.returncode != 0:
        pytest.fail(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def _all_commits() -> list[str]:
    commits = _git("rev-list", "--all").split()
    assert commits, "rev-list --all returned nothing — nothing would be scanned"
    return commits


def test_no_commit_in_history_names_the_real_clients_in_text():
    """Every text blob in every commit reachable from any ref."""
    patterns = []
    for token in scan_tokens():
        patterns += ["-e", token]
    # -I skips binaries (handled by the opaque track below); exit 1 == no match.
    out = _git("grep", "-Iil", *patterns, *_all_commits(), check=False)

    offenders = set()
    for line in out.splitlines():
        # "<commit>:<path>:..." — path may itself contain ':' , so split twice.
        parts = line.split(":", 2)
        if len(parts) < 2:
            continue
        commit, path = parts[0], parts[1]
        if path in _EXCLUDED_HOMES:
            continue  # the old token home and the probe file, by design
        offenders.add(f"{path} @ {commit[:10]}")

    assert not offenders, (
        "real-client tokens live in git HISTORY (the working tree may be "
        "clean — these are still cloned and pushed): " + ", ".join(sorted(offenders))
    )


def test_no_historical_binary_carries_a_real_client_token():
    """Opaque blobs, read through the same extractor the GOLDENS sweeps use.

    Raw bytes are deliberately NOT scanned: container formats carry vendor
    boilerplate (font tables, themes) that produces false positives a human
    then learns to ignore — and a tripwire people learn to ignore is worse
    than no tripwire."""
    from engine.intake.extract import UnreadableRfp, extract

    seen: dict[str, str] = {}
    for line in _git("rev-list", "--objects", "--all").splitlines():
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            continue
        sha, path = parts
        if Path(path).suffix.lower() in _OPAQUE_SUFFIXES:
            seen.setdefault(sha, path)
    assert seen, (
        "no opaque blobs found in history — the committed twins are binary, "
        "so an empty set means this scan is not looking where it thinks"
    )

    tokens = scan_tokens()
    offenders, unreadable, probe_hits = [], [], 0
    with tempfile.TemporaryDirectory() as tmp:
        for sha, path in sorted(seen.items(), key=lambda kv: kv[1]):
            raw = subprocess.run(
                [shutil.which("git"), "cat-file", "-p", sha],
                cwd=REPO_ROOT, capture_output=True,
            ).stdout
            scratch = Path(tmp) / f"{sha[:12]}{Path(path).suffix.lower()}"
            scratch.write_bytes(raw)
            try:
                text = extract(scratch).text.lower()
            except UnreadableRfp as exc:
                # An extension the extractor does not handle is not a pass —
                # it is an unscanned blob, and it must be named.
                unreadable.append(f"{path} @ {sha[:10]} ({exc.why})")
                continue
            probe_hits += int(_SYNTHETIC_PROBE in text)
            for token in tokens:
                if token in text:
                    offenders.append(f"{path} @ {sha[:10]}: {token!r}")

    assert not offenders, (
        f"real-client tokens inside committed binaries in history: {offenders}")
    assert not unreadable, (
        "opaque blobs in history that no extractor can read, so nothing has "
        f"scanned their contents: {unreadable}")
    # Non-vacuity: the loop above proves nothing if extraction hands back
    # empty strings. The twins all name the SYNTHETIC buyer, so finding it
    # is proof the extracted text is real content a real token could hide in.
    assert probe_hits, (
        f"no historical binary yielded the synthetic buyer name "
        f"{_SYNTHETIC_PROBE!r} — extraction is returning nothing and this "
        "scan is passing vacuously"
    )


def test_no_commit_message_or_author_names_the_real_clients():
    """History a tree scan can never see."""
    blob = _git("log", "--all", "--format=%H%n%B%n%an%n%ae%n%cn%n%ce").lower()
    # Non-vacuity: an empty log would make the scan below trivially green.
    assert len(blob.splitlines()) > len(_all_commits()), (
        "commit-message scan read less than one line per commit — it is not "
        "reading the log, and its green means nothing")
    found = [token for token in scan_tokens() if token in blob]
    assert not found, f"real-client tokens in commit messages or author identity: {found}"


def test_the_history_scan_can_actually_fail():
    """Non-vacuity: prove the text scan finds a token that IS in history,
    rather than passing because the plumbing returned nothing.

    The committed probe file is the target (B85 D4): it carries the
    synthetic probe token in every commit since it landed, so it is
    findable on ANY history depth — this repo's long one and a fresh
    single-commit public mirror alike. A scan that cannot see it is not
    scanning."""
    out = _git("grep", "-Iil", "-e", probe_token(), *_all_commits(), check=False)
    homes = {
        line.split(":", 2)[1]
        for line in out.splitlines()
        if len(line.split(":", 2)) >= 2
    }
    assert PROBE_PATH in homes, (
        f"the history scan cannot see {PROBE_PATH}, which is known to carry "
        "the synthetic probe token in every commit since B85 — the scan is "
        "broken, and its green is meaningless"
    )
