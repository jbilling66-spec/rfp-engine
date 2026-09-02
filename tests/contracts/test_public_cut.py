"""The public-cut manifest contract (P22, B85 D7).

`make public-cut` exports the allowlist (tools/public_cut/manifest.txt)
into a fresh-history staging tree; tools/public_cut/deny.txt names every
deliberate exclusion. This file pins both against the tree so the cut
cannot rot: a renamed record file, a dropped essential, or an allowlist
entry that quietly covers an exclusion is a red HERE, before any export.

Green in BOTH trees. The committed attestation
(tests/tripwire/ATTESTATION.md) exists only in the mirror — it is the
switch: the private branch of each check asserts the private discipline
(attestation untracked, deny entries real, token list ignored), the
mirror branch asserts the mirror's (attestation tracked and honored).
Every branch asserts something real; nothing skips.
"""

import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.tripwire.tokens import (
    ATTESTATION_FILE,
    ATTESTATION_SENTENCE,
    norm_ws,
)

REPO = Path(__file__).resolve().parents[2]
TOOL = REPO / "tools" / "public_cut"
SCRIPT = REPO / "tools" / "public_cut.py"
OVERLAY_ATTESTATION = TOOL / "overlay" / "tests" / "tripwire" / "ATTESTATION.md"
IS_MIRROR = ATTESTATION_FILE.exists()

# What the mirror cannot ship without — each must be covered by the
# allowlist, by name (dirs cover their contents).
_ESSENTIALS = (".github", ".gitignore", "AGENTS.md", "CLAUDE.md",
               "CONTRIBUTING.md", "LICENSE", "Makefile", "README.md",
               "SECURITY.md", "engine", "kb", "prompts", "schemas",
               "tests", "tools")


def _read_list(path: Path) -> list[str]:
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")]


def _load_tool():
    """Import tools/public_cut.py as a module (it is a script, not a
    package member). Module-level code is constants only — no side
    effects on import."""
    spec = importlib.util.spec_from_file_location("public_cut", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# Probe strings are BUILT BY CONCATENATION so this file never carries a
# literal the scanner (or a reader) could mistake for residue — the
# paraphrase law applied to the scanner's own test (B87 §4c).
def _probes() -> dict[str, bytes]:
    return {
        "underscore-default": b"bt" + b"_default",
        "underscore-default-upper": b"B" + b"T_DEFAULT",
        "underscore-reference": b"bt" + b"_reference",
        "dash-default": b"bt" + b"-default",
        "dot-internal": b"bt" + b".internal",
        "abbreviation": b"x B" + b"T y",
        "person-lower": b"x j" + b"ohn y",
    }


def test_tool_manifest_and_overlay_exist():
    assert SCRIPT.is_file(), "tools/public_cut.py is missing"
    assert (TOOL / "manifest.txt").is_file()
    assert (TOOL / "deny.txt").is_file()
    assert OVERLAY_ATTESTATION.is_file(), (
        "the overlay must carry the mirror's attestation — without it the "
        "mirror's tripwire fails on first contact")
    assert norm_ws(ATTESTATION_SENTENCE) in norm_ws(
        OVERLAY_ATTESTATION.read_text(encoding="utf-8")), (
        "the overlay attestation does not carry the exact sentence "
        "tests/tripwire/tokens.py honors — the mirror would fail loudly")


def test_every_manifest_path_exists():
    missing = [e for e in _read_list(TOOL / "manifest.txt")
               if not (REPO / e).exists()]
    assert missing == [], (
        f"allowlisted paths absent from the tree: {missing} — a rename or "
        "deletion must update the manifest deliberately")


def test_essentials_are_allowlisted():
    entries = set(_read_list(TOOL / "manifest.txt"))
    missing = [e for e in _ESSENTIALS if e not in entries]
    assert missing == [], f"essentials missing from the allowlist: {missing}"


def test_every_tracked_path_is_classified_exactly_once():
    """B92 §2a: an unclassified tracked path is an implied exclusion —
    the silent non-ship state that bit at P23 and nearly at B91. It
    REDS the suite until the ship/don't-ship call is made, and a path
    classified twice reds too (the matcher would export it and the deny
    assert would then refuse the cut)."""
    git = shutil.which("git")
    if git is None or not (REPO / ".git").exists():
        pytest.fail("this contract requires a git checkout — refusing to "
                    "pass vacuously")
    tracked = subprocess.run([git, "ls-files"], cwd=REPO, capture_output=True,
                             text=True, check=True).stdout.splitlines()
    assert tracked
    mod = _load_tool()
    uncovered, multi = mod.coverage(tracked, _read_list(TOOL / "manifest.txt"),
                                    _read_list(TOOL / "deny.txt"))
    assert uncovered == [], (
        f"unclassified tracked paths — decide ship (manifest) or don't "
        f"(deny), same commit: {uncovered}")
    assert multi == [], f"paths classified twice: {multi}"


def test_manifest_refuses_globs_like_the_deny_list():
    mod = _load_tool()
    with pytest.raises(SystemExit, match="glob"):
        mod.validate_manifest(["docs/*"])
    mod.validate_manifest(["docs", "README.md"])
    assert mod.covers("docs", "docs/a.md") and not mod.covers("docs", "docs2/a.md")


def test_no_allowlist_entry_covers_a_deny_entry():
    allow = _read_list(TOOL / "manifest.txt")
    deny = _read_list(TOOL / "deny.txt")
    covered = [(d, a) for d in deny for a in allow
               if d == a or d.startswith(a + "/")]
    assert covered == [], (
        f"deny-listed paths reachable through the allowlist: {covered} — "
        "the export would ship an excluded file")


def test_residue_baseline_detects_every_identifier_class():
    """B87 §4: the committed RESIDUE patterns catch each identifier class,
    case-insensitively where the class demands it (a deleted or weakened
    pattern is a red HERE, not a silently cleaner scan)."""
    mod = _load_tool()
    for label, probe in _probes().items():
        hit = any(rx.search(probe) for _, rx in mod.RESIDUE)
        assert hit, f"no RESIDUE pattern matches the {label} probe"


def test_the_scan_sees_filenames_and_zip_container_text(tmp_path):
    """B87 §2: the docx-title finding was invisible to a raw byte scan —
    zip containers are scanned member-by-member, and filenames are
    scanned too."""
    from docx import Document  # a hard lock pin — no conditional import

    mod = _load_tool()
    staging = tmp_path / "staging"
    staging.mkdir()
    token = (b"bt" + b"_default").decode()

    plain = staging / "note.md"
    plain.write_text(f"carries {token} in text\n", encoding="utf-8")
    named = staging / (token + ".txt")
    named.write_text("clean bytes\n", encoding="utf-8")
    doc = Document()
    doc.add_paragraph(f"body carries {token}")
    doc.save(staging / "carrier.docx")

    offenders = mod.residue_offenders(staging, mod.RESIDUE)
    assert any(o.startswith("note.md:") for o in offenders), offenders
    assert any("(filename)" in o for o in offenders), offenders
    assert any("carrier.docx!word/document.xml" in o for o in offenders), (
        f"zip member text not scanned: {offenders}")


def test_machine_local_patterns_load_and_refuse(tmp_path, monkeypatch):
    """B87 §4c: the person/firm-name class is machine state — present it
    loads case-insensitively, absent it refuses the private cut loudly,
    and only a mirror attestation excuses it (the tokens.txt posture)."""
    mod = _load_tool()
    residue = tmp_path / "residue.txt"
    attestation = tmp_path / "ATTESTATION.md"
    monkeypatch.setattr(mod, "RESIDUE_FILE", residue)
    monkeypatch.setattr(mod, "MIRROR_ATTESTATION", attestation)

    with pytest.raises(SystemExit):  # missing, no attestation: refuse
        mod.machine_patterns()

    attestation.write_text("mirror posture\n", encoding="utf-8")
    assert mod.machine_patterns() == []  # attested mirror: baseline only
    attestation.unlink()

    residue.write_text("# comment\nzz-synthetic-residue-zz\n",
                       encoding="utf-8")
    pats = mod.machine_patterns()
    assert len(pats) == 1
    name, rx = pats[0]
    assert "zz" not in name, "the offender label must not echo the pattern"
    assert rx.search(b"a ZZ-Synthetic-Residue-ZZ b"), "case fold lost"

    residue.write_text("# only comments\n", encoding="utf-8")
    with pytest.raises(SystemExit):  # present but empty: a non-decision
        mod.machine_patterns()


def test_the_self_exemption_is_exactly_the_tool_file(tmp_path):
    """B87 §2: the old exemption covered all of tools/ while its comment
    claimed one file; only tools/public_cut.py itself is exempt now."""
    mod = _load_tool()
    staging = tmp_path / "staging"
    (staging / "tools").mkdir(parents=True)
    token = (b"bt" + b"_default").decode()
    (staging / "tools" / "public_cut.py").write_text(
        f"names its own pattern {token}\n", encoding="utf-8")
    (staging / "tools" / "neighbor.txt").write_text(
        f"carries {token}\n", encoding="utf-8")

    offenders = mod.residue_offenders(staging, mod.RESIDUE)
    assert not any("public_cut.py" in o for o in offenders), offenders
    assert any("neighbor.txt" in o for o in offenders), (
        "the exemption still covers more than the tool file")


# The private working records; naming one in a shipped instruction doc
# without the private-records note leaves the mirror pointing at files
# it does not have (B87 §2 — 19 dangling references shipped that way).
_RECORD_FILES = ("DECISIONS.md", "SESSION.md", "lessons.md", "ROADMAP.md")
_PRIVATE_NOTE = ("live in the private canonical repository and do not "
                 "ship in the public mirror")
_INSTRUCTION_DOCS = (
    "CLAUDE.md", "README.md", "AGENTS.md", "CONTRIBUTING.md", "SECURITY.md",
    "kb/README.md",
    "docs/steward/maintenance-guide.md", "docs/steward/steward-runbook.md",
    "docs/steward/success-strategies.md", "docs/graph/doors.md",
    "docs/graph/modules.md", "docs/graph/artifact-flow.md",
    "docs/pilot/runbook.md", "docs/pilot/operator-guide.md",
    "docs/pilot/operator-CLAUDE.md", "docs/pilot/answering-session.md",
)


def test_docs_naming_the_records_carry_the_private_note():
    unmarked = []
    for doc in _INSTRUCTION_DOCS:
        text = (REPO / doc).read_text(encoding="utf-8")
        if any(r in text for r in _RECORD_FILES):
            if norm_ws(_PRIVATE_NOTE) not in norm_ws(text):
                unmarked.append(doc)
    assert unmarked == [], (
        f"shipped docs name a private record file without the "
        f"private-records note: {unmarked}")


def test_deny_validation_refuses_globs_and_fiction():
    """B87 §5: a deny entry with glob characters, or one covering no
    tracked file (the p14 empty-dir class), is a loud refusal in the
    tool itself — not just in this suite's drift check."""
    mod = _load_tool()
    tracked = ["docs/a.md", "docs/sub/b.md", "kept.txt"]
    mod.validate_deny(["docs/sub", "kept.txt"], tracked)  # covered: passes
    with pytest.raises(SystemExit):
        mod.validate_deny(["docs/*.md"], tracked)
    with pytest.raises(SystemExit):
        mod.validate_deny(["ghost-dir"], tracked)


def test_repo_state_matches_its_side_of_the_cut():
    git = shutil.which("git")
    if git is None or not (REPO / ".git").exists():
        pytest.fail("this contract requires a git checkout — refusing to "
                    "pass vacuously")

    def tracked(path: str) -> bool:
        return subprocess.run(
            [git, "ls-files", "--error-unmatch", path],
            cwd=REPO, capture_output=True).returncode == 0

    if IS_MIRROR:
        # The mirror: the attestation is a TRACKED file (the overlay landed
        # in the one public commit), and no deny-listed path shipped.
        assert tracked("tests/tripwire/ATTESTATION.md"), (
            "mirror state: the attestation exists but is untracked — the "
            "cut did not commit it")
        shipped = [e for e in _read_list(TOOL / "deny.txt")
                   if (REPO / e).exists()]
        assert shipped == [], f"deny-listed paths shipped: {shipped}"
    else:
        # The private tree: the attestation must NEVER exist (a lost token
        # list must fail loudly, not attest itself away); every deny entry
        # is real (the list cannot rot into fiction); the token list stays
        # untrackable.
        assert not ATTESTATION_FILE.exists(), (
            "tests/tripwire/ATTESTATION.md exists in the PRIVATE tree — "
            "it would let a lost token list pass vacuously; delete it "
            "(the overlay copy under tools/public_cut/ is its only home "
            "here)")
        # Tracked coverage, not bare existence: an empty working-tree dir
        # satisfied `.exists()` while no clone ever had it (the p14 class
        # CI caught, B87 §5).
        tracked_paths = subprocess.run(
            [git, "ls-files"], cwd=REPO, capture_output=True,
            text=True).stdout.splitlines()
        uncovered = [e for e in _read_list(TOOL / "deny.txt")
                     if not any(t == e or t.startswith(e + "/")
                                for t in tracked_paths)]
        assert uncovered == [], (
            f"deny entries covering no tracked file: {uncovered} — prune "
            "the deny list deliberately or the exclusion intent is fiction")
        ignored = subprocess.run(
            [git, "check-ignore", "-q", "tripwire-local/tokens.txt"],
            cwd=REPO).returncode == 0
        assert ignored, "tripwire-local/ must stay gitignored"


# --- the two history modes (B89 §4a) -----------------------------------
# fresh_history is the first-publication shape; release_commit is the
# update path — one commit appended to the PUBLISHED history so adopters
# tracking the mirror can pull releases. Both run on synthetic tmp repos
# under the tool's own scrubbed env.

def _git(mod, cwd, *args):
    _, base_env, _ = mod.release_identity()
    r = subprocess.run(["git", "-c", "commit.gpgsign=false",
                        "-c", "core.hooksPath=", *args],
                       cwd=cwd, env=base_env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _seed_public(mod, tmp_path):
    """A published mirror stand-in: one prior neutral commit on main."""
    pub = tmp_path / "published"
    pub.mkdir()
    (pub / "README.md").write_text("release zero\n")
    (pub / "stale.txt").write_text("to be deleted\n")
    _, _, env = mod.release_identity()
    _git(mod, pub, "init", "-q")
    _git(mod, pub, "symbolic-ref", "HEAD", "refs/heads/main")
    _git(mod, pub, "add", "-A")
    subprocess.run(["git", "-c", "commit.gpgsign=false",
                    "-c", "core.hooksPath=", "commit", "-q", "-m",
                    "Initial public release"],
                   cwd=pub, env=env, check=True)
    return pub


def test_fresh_history_is_a_single_neutral_commit(tmp_path, monkeypatch):
    """Pin the default mode now that a second mode exists: a brand-new
    history, exactly one commit, neutral identity, branch main."""
    monkeypatch.delenv("PUBLIC_CUT_AUTHOR", raising=False)
    mod = _load_tool()
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "README.md").write_text("cut\n")
    author = mod.fresh_history(staging)
    assert author == mod.DEFAULT_AUTHOR
    assert _git(mod, staging, "rev-list", "--count", "HEAD") == "1"
    assert _git(mod, staging, "symbolic-ref", "--short", "HEAD") == "main"
    an, cn, subject = _git(mod, staging, "log", "-1",
                           "--format=%an <%ae>|%cn <%ce>|%s").split("|")
    assert an == mod.DEFAULT_AUTHOR and cn == mod.DEFAULT_AUTHOR
    assert subject == "Initial public release"


def test_release_commit_appends_onto_the_existing_history(tmp_path,
                                                          monkeypatch):
    """Parent = the published HEAD; the tree becomes exactly the staging
    tree (adds, changes, AND deletions); the identity stays neutral; the
    clone keeps its origin remote so the printed push step is real."""
    monkeypatch.delenv("PUBLIC_CUT_AUTHOR", raising=False)
    mod = _load_tool()
    pub = _seed_public(mod, tmp_path)
    prior_head = _git(mod, pub, "rev-parse", "HEAD")
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "README.md").write_text("release one\n")   # changed
    (staging / "engine.txt").write_text("new file\n")     # added
    # stale.txt intentionally absent                      # deleted
    rel, author = mod.release_commit(staging, str(pub),
                                     release_dir=tmp_path / "rel",
                                     acknowledged={"stale.txt"})  # B92 §2b
    assert author == mod.DEFAULT_AUTHOR
    assert _git(mod, rel, "rev-parse", "HEAD^") == prior_head
    assert set(_git(mod, rel, "ls-files").splitlines()) == {"README.md",
                                                            "engine.txt"}
    assert (rel / "README.md").read_text() == "release one\n"
    assert not (rel / "stale.txt").exists()
    assert _git(mod, rel, "log", "-1",
                "--format=%s").startswith("Public release: ")
    assert _git(mod, rel, "remote", "get-url", "origin") == str(pub)


def test_release_refuses_an_unacknowledged_deletion(tmp_path, monkeypatch):
    """B92 §2b: a published file absent from the cut is a loud stop unless
    acknowledged by name; the acknowledgment file is the record."""
    monkeypatch.delenv("PUBLIC_CUT_AUTHOR", raising=False)
    mod = _load_tool()
    pub = _seed_public(mod, tmp_path)
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "README.md").write_text("release one\n")
    with pytest.raises(SystemExit) as exc:
        mod.release_commit(staging, str(pub), release_dir=tmp_path / "rel1")
    assert "NOT acknowledged" in str(exc.value) and "stale.txt" in str(exc.value)
    assert _git(mod, pub, "rev-list", "--count", "HEAD") == "1"  # untouched
    # the committed list is the default source of acknowledgments
    monkeypatch.setattr(mod, "DELETIONS", tmp_path / "deletions.txt")
    (tmp_path / "deletions.txt").write_text("# ack\nstale.txt\n")
    rel, _ = mod.release_commit(staging, str(pub), release_dir=tmp_path / "rel2")
    assert not (rel / "stale.txt").exists()


def test_release_refuses_a_fictional_acknowledgment(tmp_path, monkeypatch):
    monkeypatch.delenv("PUBLIC_CUT_AUTHOR", raising=False)
    mod = _load_tool()
    pub = _seed_public(mod, tmp_path)
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "README.md").write_text("release one\n")
    (staging / "stale.txt").write_text("to be deleted\n")  # NOT deleted
    with pytest.raises(SystemExit) as exc:
        mod.release_commit(staging, str(pub), release_dir=tmp_path / "rel",
                           acknowledged={"stale.txt"})
    assert "fiction" in str(exc.value)


def test_release_commit_refuses_empty_delta_and_unpublished_target(
        tmp_path, monkeypatch):
    """No empty releases, and no 'updating' a repo that was never
    published — the initial release is the fresh-history default."""
    monkeypatch.delenv("PUBLIC_CUT_AUTHOR", raising=False)
    mod = _load_tool()
    pub = _seed_public(mod, tmp_path)
    same = tmp_path / "same"
    same.mkdir()
    (same / "README.md").write_text("release zero\n")
    (same / "stale.txt").write_text("to be deleted\n")
    with pytest.raises(SystemExit) as exc:
        mod.release_commit(same, str(pub), release_dir=tmp_path / "rel1")
    assert "nothing to release" in str(exc.value)

    empty = tmp_path / "unpublished"
    empty.mkdir()
    _git(mod, empty, "init", "-q")
    with pytest.raises(SystemExit) as exc:
        mod.release_commit(same, str(empty), release_dir=tmp_path / "rel2")
    assert "no tracked files" in str(exc.value)
