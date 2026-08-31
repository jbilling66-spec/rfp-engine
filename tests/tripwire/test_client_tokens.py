"""The synthetic-data boundary (CLAUDE.md rule 1, spec rule 5).

Real-client tokens appear in NO tracked file (B85 D3 — until then this
file itself was the one allowed home, v1's brand-test precedent): the
list lives in the gitignored ``tripwire-local/tokens.txt`` and reaches
the scans through ``tests.tripwire.tokens``, which fails loudly when the
list is missing and appends a committed synthetic probe so every scan
stays exercised. Everything tracked refers to fixtures by their neutral
ids (hosp-erp, otas-bid). fixtures-local/ stays gitignored and, until
the A1 real-data gate opens, empty ON DISK except the attested pens
(tested below, not just untracked).

Coverage is closed (B30): every tracked file is either raw-text-scanned
(no suffix allowlist — Makefile, .gitignore, requirements.lock included)
or an opaque binary that MUST appear in the extraction-sweep goldens
(tests/fixtures/test_twins.py + tests/intake/test_fixtures.py sweep the
extracted text of every GOLDENS entry). A newly committed binary type
fails here until it is extraction-swept. No git → loud failure, never a
vacuous pass.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

from tests.tripwire.tokens import PROBE_PATH, scan_tokens

REPO_ROOT = Path(__file__).resolve().parents[2]

# Formats whose committed bytes can hide text from a raw scan (zip/stream
# containers). Anything matching — by suffix or by NUL bytes in content —
# must be covered by an extraction sweep, or the closure test fails.
_OPAQUE_SUFFIXES = {".xlsx", ".xlsm", ".docx", ".pptx", ".pdf", ".zip",
                    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff", ".woff2"}


def _tracked_files() -> list[str]:
    git = shutil.which("git")
    if git is None or not (REPO_ROOT / ".git").exists():
        pytest.fail(
            "tripwire requires a git checkout: no git binary or no .git dir — "
            "refusing to pass vacuously (CLAUDE.md rule 1 would be unenforced)"
        )
    out = subprocess.run(
        [git, "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout
    files = out.splitlines()
    assert files, "git ls-files returned nothing — tripwire has nothing to scan"
    return files


def _is_opaque(path: Path) -> bool:
    return path.suffix.lower() in _OPAQUE_SUFFIXES or b"\x00" in path.read_bytes()


def _extraction_swept() -> set[str]:
    """The binaries the extraction sweeps actually cover — read from the live
    GOLDENS dicts so a new golden joins automatically and a renamed one fails."""
    from tests.fixtures.docx_twins import GOLDENS as docx_goldens
    from tests.fixtures.intake_twins import GOLDENS as intake_goldens
    from tests.fixtures.twins import GOLDENS as twin_goldens

    # Config binaries with their own pin + sweep tests (P16/C7: the firm
    # template is committed CONFIG — tests/fixtures/test_docx_twins.py
    # pins its bytes to the builder and sweeps its extracted text).
    config_binaries = {"config/templates/firm-default-template.docx"}
    return {f"tests/fixtures/{name}"
            for name in (*twin_goldens, *intake_goldens, *docx_goldens)
            } | config_binaries


def test_gitignore_covers_fixtures_local_and_pursuits():
    """Asserts the BEHAVIOUR, not the literal line: the rule that matters
    is that live workspaces and real fixtures cannot be committed, and a
    text match cannot tell an anchored pattern from a weakened one. (The
    P10 metrics fixture forced `/pursuits/` — an unanchored `pursuits/`
    matches at every depth and swallowed tests/fixtures/pursuits/ too.)"""
    git = shutil.which("git")
    if git is None or not (REPO_ROOT / ".git").exists():
        pytest.fail("tripwire requires a git checkout — refusing to pass "
                    "vacuously (CLAUDE.md rule 1 would be unenforced)")

    def ignored(path: str) -> bool:
        return subprocess.run(
            [git, "check-ignore", "-q", path], cwd=REPO_ROOT
        ).returncode == 0

    assert ignored("fixtures-local/anything.xlsx")
    assert ignored("pursuits/pur_live/brief.json"), (
        "the live workspace must stay ignored — real client material "
        "lands there first")
    # ...and the anchoring must not have swallowed the committed corpus
    # the resolver is measured against (B40/D13).
    assert not ignored("tests/fixtures/pursuits/pur_metrics/brief.json")
    # ...and the handoff exchange files stay untrackable at ANY depth:
    # buyer prompt text lands in pending-calls/ under whatever workspace
    # the operator names, not only the /pursuits/-anchored default
    # (B83 D8; unanchored on purpose — nothing committed carries the name).
    assert ignored("elsewhere/pending-calls/call-0001.request.json"), (
        "pending-calls/ must be ignored at every depth — a non-default "
        "--workspace would otherwise put buyer prompt text in tracked space")
    # ...and the restricted-token list itself can never be committed (B85
    # D3): the externalized list is only safe if git refuses to track it.
    assert ignored("tripwire-local/tokens.txt"), (
        "tripwire-local/ must be gitignored — the restricted-token list is "
        "the one file whose committing would be the disclosure the whole "
        "tripwire exists to prevent")


def test_no_fixtures_local_file_is_tracked():
    tracked = [f for f in _tracked_files() if f.startswith("fixtures-local")]
    assert tracked == [], f"real fixtures are TRACKED: {tracked}"


# B71: the two attested pens — the ONLY space in fixtures-local/ that may
# hold files before A1. prospect/ = PUBLIC solicitation documents;
# firm/ = the firm's own template. Everything else stays empty on disk.
_ATTESTED_PENS = ("prospect", "firm")


def test_fixtures_local_holds_only_attested_material():
    """CLAUDE.md rule 3 (amended B71) says 'stays empty', not 'stays
    untracked' — a document dropped elsewhere would be gitignored and
    invisible to the tracked-file scan. The carved exception (rule 1, B71):
    the prospect/ and firm/ pens may hold files IF each file carries a
    NEUTRAL filename (token-clean — the real names are the risk) and is
    listed in its pen's MANIFEST.md (source attested, not verified — B68's
    honest limit). A1 retires this test under the anonymization controls."""
    root = REPO_ROOT / "fixtures-local"
    if not root.exists():
        return
    for path in [p for p in root.rglob("*") if p.is_file()]:
        rel = path.relative_to(root)
        pen = rel.parts[0] if len(rel.parts) > 1 else None
        assert pen in _ATTESTED_PENS, (
            f"fixtures-local/{rel} sits outside the attested pens "
            f"{_ATTESTED_PENS} — that space stays empty until the A1 "
            f"real-data gate")
        lowered = path.name.lower()
        hits = [t for t in scan_tokens() if t in lowered]
        assert not hits, (
            f"fixtures-local/{rel}: filename carries a listed token — "
            f"deposit under a neutral id (B67 handling note; the manifest "
            f"carries the real provenance)")
        if path.name == "MANIFEST.md":
            continue
        manifest = root / pen / "MANIFEST.md"
        assert manifest.exists(), (
            f"fixtures-local/{pen}/ holds files but no MANIFEST.md — every "
            f"deposit is attested with its public source + retrieval date")
        assert path.name in manifest.read_text(encoding="utf-8"), (
            f"fixtures-local/{rel} is not listed in {pen}/MANIFEST.md — "
            f"an unattested file is indistinguishable from a leak")


def test_every_tracked_binary_is_extraction_swept():
    """Closure: raw text scanning cannot see inside container formats, so every
    opaque tracked file must be named in a GOLDENS dict whose extracted text
    the fixture suites sweep. New binary in the repo → this fails until it is."""
    swept = _extraction_swept()
    unswept = []
    for rel in _tracked_files():
        path = REPO_ROOT / rel
        if not path.exists():  # tracked-but-deleted mid-change
            continue
        if _is_opaque(path) and rel not in swept:
            unswept.append(rel)
    assert unswept == [], (
        f"tracked binaries no sweep covers (add to a GOLDENS extraction sweep "
        f"or don't commit them): {unswept}"
    )


def test_no_committed_file_names_the_real_clients():
    tokens = scan_tokens()
    offenders = []
    for rel in _tracked_files():
        path = REPO_ROOT / rel
        if not path.exists():  # tracked-but-deleted mid-change
            continue
        if rel == PROBE_PATH or _is_opaque(path):
            # The probe file carries its own token by design; opaque files
            # are covered by the extraction sweeps.
            continue
        text = path.read_bytes().decode("utf-8", errors="ignore").lower()
        for token in tokens:
            if token in text:
                offenders.append(f"{rel}: {token!r}")
    assert offenders == [], f"real-client tokens in tracked files: {offenders}"
