"""Build and verify the fresh-history public mirror (P22, B85).

`make public-cut` runs this. The flow, each step refusing loudly:

  1. clean HEAD required — the cut is of a committed tree, never a dirty one
  2. `git archive HEAD` of the allowlisted paths (tools/public_cut/
     manifest.txt) into a fresh staging dir — git plumbing, never a
     working-tree copy, so untracked and gitignored material (real
     solicitation documents in fixtures-local/, GB-scale models/) cannot
     leak by construction
  3. the mirror-only overlay (tools/public_cut/overlay/) is applied — it
     carries tests/tripwire/ATTESTATION.md, the mirror's explicit
     empty-token-list posture (the private repo must NEVER commit it)
  4. the deny list (tools/public_cut/deny.txt) is asserted absent and the
     residue scan sweeps every staged file — contents, filenames, and the
     decompressed text members of zip containers (docx/xlsx) — for the
     committed identifier baseline plus the machine-local person/firm
     patterns in tripwire-local/residue.txt (gitignored; required to cut
     the private tree, B87 §4c)
  5. history, one commit under a neutral identity either way (override
     with PUBLIC_CUT_AUTHOR="Name <email>") — the history tripwire scans
     author, committer, and message, so neutrality is load-bearing. The
     default is `git init` + ONE commit on a brand-new history (the
     initial release). With PUBLIC_CUT_RELEASE=<published repo path or
     URL>, the verified tree is instead committed ONTO that repo's
     existing history — clone, replace content wholesale, one release
     commit — the update path for adopters tracking the published mirror
     (B89 §4a)
  6. the FULL suite runs inside the tree that would be pushed (staging,
     or the release clone) and must be green
  7. the manual next steps print — the push is a human act, never this
     script's (B85: the public push waits on the owner's explicit go)

Staging goes to a fresh temp dir (override: PUBLIC_CUT_DIR, which must not
already exist — this script never deletes a directory it did not create).
Release mode clones into a second fresh temp dir; the push stays manual in
both modes.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL_DIR = ROOT / "tools" / "public_cut"
MANIFEST = TOOL_DIR / "manifest.txt"
DENY = TOOL_DIR / "deny.txt"
DELETIONS = TOOL_DIR / "deletions.txt"  # release-mode deletion acknowledgments
OVERLAY = TOOL_DIR / "overlay"

DEFAULT_AUTHOR = "RFP Engine Maintainers <rfp-engine@invalid>"

# Firm identifiers that must not survive into the mirror, plus the
# person-name check. The tripwire covers restricted CLIENT tokens; this
# scan covers the build's own residue classes (B85 §3, D6). The committed
# baseline carries ONLY patterns whose text already lives in tracked files;
# the personal/firm-NAME class (surname, username, firm words) is machine
# state in tripwire-local/residue.txt — the paraphrase law (CLAUDE.md
# rule 6) binds the scanner too (B87 §4c).
RESIDUE = [
    ("bt_default", re.compile(rb"bt_default", re.I)),
    ("bt_reference", re.compile(rb"bt_reference", re.I)),
    ("bt-default", re.compile(rb"bt-default", re.I)),
    ("bt.internal", re.compile(rb"bt\.internal", re.I)),
    # Uppercase-only: the standalone firm abbreviation (the docx title
    # finding, B87 §2); lowercase standalone "bt" is everyday byte noise.
    ("BT", re.compile(rb"\bBT\b")),
    ("John", re.compile(rb"\bjohn\b", re.I)),
]

RESIDUE_FILE = ROOT / "tripwire-local" / "residue.txt"
MIRROR_ATTESTATION = ROOT / "tests" / "tripwire" / "ATTESTATION.md"

# Zip containers hold their text deflate-compressed — a raw byte scan is
# blind to it (the B87 docx-title finding). Their TEXT members are scanned
# decompressed; binary members (thumbnails, fonts) are skipped because
# word-boundary patterns false-positive on arbitrary bytes.
_ZIP_SUFFIXES = {".docx", ".xlsx", ".pptx", ".zip"}
_ZIP_TEXT_MEMBER = (".xml", ".rels", ".txt", ".md", ".json", ".csv")

# "BT" is also the PDF begin-text operator; the abbreviation pattern skips
# .pdf files (the committed PDF twins carry uncompressed streams, so the
# other patterns still see their text raw) — and the two SOURCE files that
# emit that operator when building PDF content streams (named, not a
# directory: a new emitter is an explicit addition here).
_PDF_EXEMPT = {"BT"}
_PDF_OPERATOR_EMITTERS = {
    "engine/extraction/corpus.py",
    "tests/fixtures/intake_twins.py",
}


def machine_patterns() -> list[tuple[str, re.Pattern]]:
    """The machine-local residue class (B87 §4c): person/firm-name
    substrings, one per line, ``#`` comments allowed, matched
    case-insensitively. Required to cut the private tree; a mirror
    checkout (committed attestation) runs on the baseline alone —
    the same posture split as tripwire-local/tokens.txt."""
    if not RESIDUE_FILE.exists():
        if MIRROR_ATTESTATION.exists():
            return []
        sys.exit(
            "FAILED: tripwire-local/residue.txt is missing — the scan's "
            "person/firm-name patterns are machine state (the paraphrase "
            "law keeps them out of tracked files, B87 §4c). Create it: one "
            "case-insensitive substring per line (# comments allowed) "
            "naming the person and firm strings that must never ship, "
            "then rerun."
        )
    lines = read_list(RESIDUE_FILE)
    if not lines:
        sys.exit(
            "FAILED: tripwire-local/residue.txt exists but lists no "
            "patterns — an empty file is a decision, not a default: name "
            "the patterns or delete the file (a mirror checkout runs on "
            "its committed attestation instead)."
        )
    # Offender labels never echo the pattern — a scan report is exactly
    # the kind of text that gets pasted somewhere tracked.
    return [(f"machine-local #{i}", re.compile(re.escape(line).encode(), re.I))
            for i, line in enumerate(lines, start=1)]


def residue_offenders(staging: Path,
                      patterns: list[tuple[str, re.Pattern]]) -> list[str]:
    offenders = []
    for path in sorted(staging.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(staging)
        if str(rel) == "tools/public_cut.py":
            # This file necessarily NAMES the baseline patterns it scans
            # for — the ONE self-exemption (narrowed at B87 §2 from the
            # whole tools/ subtree the old comment never claimed).
            continue
        active = [(name, rx) for name, rx in patterns
                  if not (name in _PDF_EXEMPT
                          and (path.suffix.lower() == ".pdf"
                               or str(rel) in _PDF_OPERATOR_EMITTERS))]
        for name, rx in active:
            if rx.search(str(rel).encode()):
                offenders.append(f"{rel} (filename): {name}")
        blobs = [(str(rel), path.read_bytes())]
        if path.suffix.lower() in _ZIP_SUFFIXES:
            with zipfile.ZipFile(path) as zf:
                blobs += [(f"{rel}!{m}", zf.read(m)) for m in zf.namelist()
                          if m.lower().endswith(_ZIP_TEXT_MEMBER)]
        for label, data in blobs:
            for name, rx in active:
                if rx.search(data):
                    offenders.append(f"{label}: {name}")
    return offenders


def read_list(path: Path) -> list[str]:
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            entries.append(line)
    return entries


def run(*args: str, cwd: Path, env: dict | None = None,
        check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(args, cwd=cwd, env=env, capture_output=True,
                            text=True)
    if check and result.returncode != 0:
        sys.exit(f"FAILED: {' '.join(args)}\n{result.stderr.strip()}")
    return result


def covers(entry: str, path: str) -> bool:
    """The ONE matcher for manifest and deny entries: a literal path, or
    a directory prefix. Globs are refused at validation, so this is the
    whole semantics."""
    return path == entry or path.startswith(entry + "/")


def validate_manifest(entries: list[str]) -> None:
    """Mirror of validate_deny's glob rule for the allowlist: `git archive`
    would accept a glob pathspec, but the coverage matcher would not see
    it — the two must agree, so globs are refused on both lists."""
    for entry in entries:
        if any(ch in entry for ch in "*?["):
            sys.exit(f"FAILED: manifest entry {entry!r} uses glob characters "
                     "— name the real path or directory")


def coverage(tracked: list[str], manifest: list[str],
             deny: list[str]) -> tuple[list[str], list[str]]:
    """B92 §2a: every tracked path is classified by EXACTLY ONE entry of
    manifest ∪ deny. Returns (uncovered, covered_more_than_once). An
    uncovered path is an implied exclusion — the silent-non-ship state
    that bit at P23 and nearly at B91; it no longer exists as a state."""
    entries = list(manifest) + list(deny)
    uncovered, multi = [], []
    for path in tracked:
        hits = sum(1 for e in entries if covers(e, path))
        if hits == 0:
            uncovered.append(path)
        elif hits > 1:
            multi.append(path)
    return uncovered, multi


def validate_deny(entries: list[str], tracked: list[str]) -> None:
    """Every deny entry must cover at least one TRACKED file: `.exists()`
    was satisfied by an empty working-tree dir no clone ever has (the p14
    class CI caught, B87 §5), and glob characters silently matched
    nothing at all."""
    for entry in entries:
        if any(ch in entry for ch in "*?["):
            sys.exit(f"FAILED: deny entry {entry!r} uses glob characters — "
                     "the deny check matches literal paths only; name the "
                     "real path or directory")
        if not any(covers(entry, t) for t in tracked):
            sys.exit(f"FAILED: deny entry {entry!r} covers no tracked file "
                     "— an exclusion of nothing is fiction; prune it "
                     "deliberately (the p14 lesson, B87 §5)")


def release_identity() -> tuple[str, dict, dict]:
    """The neutral commit identity both history modes share: the author
    string, a base env scrubbed of inherited GIT_* state, and that env
    with the identity applied."""
    author = os.environ.get("PUBLIC_CUT_AUTHOR", DEFAULT_AUTHOR)
    m = re.fullmatch(r"(.+?)\s*<(.+)>", author)
    if not m:
        sys.exit(f'FAILED: PUBLIC_CUT_AUTHOR must be "Name <email>", '
                 f"got {author!r}")
    identity = {
        "GIT_AUTHOR_NAME": m.group(1), "GIT_AUTHOR_EMAIL": m.group(2),
        "GIT_COMMITTER_NAME": m.group(1), "GIT_COMMITTER_EMAIL": m.group(2),
    }
    # The history repos must not inherit the invoking user's git state:
    # GIT_* vars could redirect the init, a global commit.gpgsign would
    # fail the neutral identity (no key), and global hooks must not fire.
    base_env = {k: v for k, v in os.environ.items()
                if not k.startswith("GIT_")}
    return author, base_env, {**base_env, **identity}


_NEUTRAL = ("git", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=")


def fresh_history(staging: Path) -> str:
    """The first-publication shape: ONE commit on a brand-new history."""
    author, base_env, env = release_identity()
    run(*_NEUTRAL, "init", "-q", cwd=staging, env=base_env)
    run(*_NEUTRAL, "symbolic-ref", "HEAD", "refs/heads/main", cwd=staging,
        env=base_env)
    run(*_NEUTRAL, "add", "-A", cwd=staging, env=base_env)
    run(*_NEUTRAL, "commit", "-q", "-m", "Initial public release",
        cwd=staging, env=env)
    return author


def staged_paths(staging: Path) -> set[str]:
    return {p.relative_to(staging).as_posix() for p in staging.rglob("*")
            if p.is_file() and ".git" not in p.relative_to(staging).parts}


def release_commit(staging: Path, target: str,
                   release_dir: Path | None = None,
                   acknowledged: set[str] | None = None) -> tuple[Path, str]:
    """The update path (B89 §4a): commit the verified staging tree ONTO
    the existing public history — clone the published repo, replace its
    tracked content wholesale, one neutral release commit. An unchanged
    tree refuses loudly rather than minting an empty release.

    The deletion guard (B92 §2b, P25 item 7): every file in the published
    HEAD that is absent from the staged cut must be ACKNOWLEDGED in
    tools/public_cut/deletions.txt (or `acknowledged`), else the release
    refuses naming each surprise path — a contributor's merged work that
    was never back-ported used to vanish silently under the wholesale
    replace. An acknowledged path that is NOT a deletion refuses too (the
    p14 fiction rule): the list is emptied after each release."""
    author, base_env, env = release_identity()
    if release_dir is None:
        release_dir = Path(tempfile.mkdtemp(prefix="rfp-public-release-"))
    run(*_NEUTRAL, "clone", "-q", target, str(release_dir), cwd=ROOT,
        env=base_env)
    published = set(run("git", "ls-files", cwd=release_dir,
                        env=base_env).stdout.splitlines())
    if not published:
        sys.exit(f"FAILED: PUBLIC_CUT_RELEASE target {target!r} has no "
                 "tracked files — release mode updates a PUBLISHED mirror; "
                 "the initial release is the default fresh-history cut")
    if acknowledged is None:
        acknowledged = set(read_list(DELETIONS)) if DELETIONS.exists() else set()
    deletions = published - staged_paths(staging)
    surprise = sorted(deletions - acknowledged)
    fiction = sorted(acknowledged - deletions)
    if surprise:
        sys.exit("FAILED: the published mirror holds files absent from "
                 "this cut and NOT acknowledged in "
                 f"{DELETIONS.name}: {surprise} — back-port them or list "
                 "each one deliberately (B92 §2b)")
    if fiction:
        sys.exit(f"FAILED: {DELETIONS.name} acknowledges paths that are "
                 f"not deletions in this cut: {fiction} — an "
                 "acknowledgment of nothing is fiction; prune it")
    run(*_NEUTRAL, "rm", "-rq", ".", cwd=release_dir, env=base_env)
    shutil.copytree(staging, release_dir, dirs_exist_ok=True)
    run(*_NEUTRAL, "add", "-A", cwd=release_dir, env=base_env)
    if not run("git", "status", "--porcelain", cwd=release_dir,
               env=base_env).stdout.strip():
        sys.exit("FAILED: nothing to release — the public repo already "
                 "matches this cut")
    head = run("git", "rev-parse", "--short", "HEAD", cwd=ROOT).stdout.strip()
    run(*_NEUTRAL, "commit", "-q", "-m", f"Public release: {head}",
        cwd=release_dir, env=env)
    return release_dir, author


def main() -> None:
    dirty = run("git", "status", "--porcelain", cwd=ROOT).stdout.strip()
    if dirty:
        sys.exit("FAILED: the tree is dirty — the cut is of a committed "
                 "HEAD only:\n" + dirty)

    # Refusals that need no staging happen BEFORE any export work.
    patterns = RESIDUE + machine_patterns()
    tracked = run("git", "ls-files", cwd=ROOT).stdout.splitlines()
    validate_manifest(read_list(MANIFEST))
    validate_deny(read_list(DENY), tracked)
    uncovered, multi = coverage(tracked, read_list(MANIFEST), read_list(DENY))
    if uncovered or multi:
        sys.exit("FAILED: every tracked path must be classified by exactly "
                 "one manifest/deny entry (B92 §2a)\n"
                 + ("  unclassified (ship or deny — decide): "
                    f"{uncovered}\n" if uncovered else "")
                 + (f"  classified twice: {multi}\n" if multi else ""))

    override = os.environ.get("PUBLIC_CUT_DIR")
    if override:
        staging = Path(override)
        if staging.exists():
            sys.exit(f"FAILED: PUBLIC_CUT_DIR {staging} already exists — "
                     "this script never deletes a directory it did not "
                     "create; remove it yourself and rerun")
        if staging.resolve().is_relative_to(ROOT):
            sys.exit(f"FAILED: PUBLIC_CUT_DIR {staging} is inside the "
                     "repo — a nested git init would dirty the working "
                     "tree; stage outside it")
        staging.mkdir(parents=True)
    else:
        staging = Path(tempfile.mkdtemp(prefix="rfp-public-cut-"))
    print(f"staging: {staging}")

    try:
        _build_and_verify(staging, patterns)
    except SystemExit:
        # Never silent litter: a failed run names what it left behind.
        print(f"NOTE: staging left for inspection at {staging}",
              file=sys.stderr)
        raise


def _verify_suite(verify_dir: Path) -> None:
    """The suite-green gate, as its own seam (P1-18): the orchestration
    tests stub THIS function, never subprocess — the import-provenance
    probe and the pytest run stay exactly what a live cut runs."""
    probe = run(sys.executable, "-c",
                "import engine; print(engine.__file__)", cwd=verify_dir)
    probe_path = Path(probe.stdout.strip()).resolve()
    if not probe_path.is_relative_to(verify_dir.resolve()):
        sys.exit("FAILED: the verification suite would import engine from "
                 f"outside the cut tree ({probe.stdout.strip()}) — refusing "
                 "to verify the wrong tree")

    print("running the full suite in the cut tree (this takes a few "
          "minutes)…")
    suite = subprocess.run([sys.executable, "-m", "pytest", "-q"],
                           cwd=verify_dir, capture_output=True, text=True)
    tail = "\n".join(suite.stdout.splitlines()[-3:])
    print(tail)
    if suite.returncode != 0:
        sys.exit("FAILED: the cut tree's suite is not green — the mirror "
                 "does not ship red")



def _build_and_verify(staging: Path,
                      patterns: list[tuple[str, re.Pattern]]) -> None:
    manifest = read_list(MANIFEST)
    archive = subprocess.Popen(
        ["git", "archive", "HEAD", "--", *manifest],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    tar = subprocess.run(["tar", "-x", "-C", str(staging)],
                         stdin=archive.stdout, capture_output=True)
    archive.stdout.close()
    if archive.wait() != 0 or tar.returncode != 0:
        # A pathspec typo used to fail contentless — carry both stderrs.
        sys.exit("FAILED: git archive | tar export\n"
                 + archive.stderr.read().decode(errors="replace").strip()
                 + "\n" + tar.stderr.decode(errors="replace").strip())

    # The overlay may only ADD files; shadowing an exported one would be
    # a silent content swap.
    for src in OVERLAY.rglob("*"):
        if src.is_file():
            dest = staging / src.relative_to(OVERLAY)
            if dest.exists():
                sys.exit("FAILED: the overlay would overwrite exported "
                         f"{dest.relative_to(staging)} — overlay files "
                         "must not collide with the manifest")
    shutil.copytree(OVERLAY, staging, dirs_exist_ok=True)
    print(f"exported {sum(1 for p in staging.rglob('*') if p.is_file())} "
          "files + overlay")

    denied = [entry for entry in read_list(DENY)
              if (staging / entry).exists()]
    if denied:
        sys.exit(f"FAILED: deny-listed paths present in staging: {denied}")

    offenders = residue_offenders(staging, patterns)
    if offenders:
        sys.exit("FAILED: residue in the staging tree:\n  "
                 + "\n  ".join(offenders))
    print("residue scan: clean")

    release_target = os.environ.get("PUBLIC_CUT_RELEASE")
    if release_target:
        verify_dir, author = release_commit(staging, release_target)
        print(f"release history: 1 new commit onto {release_target} "
              f"as {author}")
    else:
        verify_dir = staging
        author = fresh_history(staging)
        print(f"fresh history: 1 commit as {author}")

    _verify_suite(verify_dir)
    # An annotated tag records a TAGGER identity from the local git
    # config — outside this script's scrubbed env. The printed steps
    # carry the neutral identity so following them verbatim cannot leak
    # the operator's name (caught live at the P24 publish, B90).
    name, email = re.fullmatch(r"(.+?)\s*<(.+)>", author).groups()
    tag_env = (f'GIT_COMMITTER_NAME="{name}" '
               f'GIT_COMMITTER_EMAIL="{email}"')
    if release_target:
        print(f"""
PUBLIC CUT VERIFIED at {verify_dir} (release mode — one commit appended
to the existing public history)

Next steps (manual, owner-gated — never automated):
  1. cd {verify_dir}
  2. review: git log --stat -1
  3. git push origin main
  4. if this release warrants a tag:
     {tag_env} git tag -a <version> -m "<title>"
     then git push --tags — a bare `git tag -a` would record YOUR
     identity as the tagger; it must stay as neutral as the commits
""")
    else:
        print(f"""
PUBLIC CUT VERIFIED at {staging}

Next steps (manual, owner-gated — never automated):
  1. create the public GitHub repository (name is the owner's call)
  2. cd {staging}
  3. git remote add origin <public repo url>
  4. {tag_env} git tag -a v0.1.0 -m "Initial public release"
     (the env matters: a bare `git tag -a` records YOUR identity as
     the tagger; it must stay as neutral as the commits)
  5. git push -u origin main --tags
""")


if __name__ == "__main__":
    main()
