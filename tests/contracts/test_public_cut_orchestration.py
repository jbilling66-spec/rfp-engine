"""P1-18 (P25 item 7): the public-cut ORCHESTRATION guards proven on a
synthetic repository — dirty tree, coverage, overlay collision, deny in
staging, suite red, and the happy path — not only by live dry runs.
The suite-green leg is a named seam (`_verify_suite`); these tests stub
that function, never subprocess."""

import os
import subprocess

import pytest

from tests.contracts.test_public_cut import _git, _load_tool, _seed_public


def _commit_all(mod, repo, message):
    _git(mod, repo, "add", "-A")
    _, _, env = mod.release_identity()
    subprocess.run(["git", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=",
                    "commit", "-q", "-m", message], cwd=repo, env=env, check=True)


def _synthetic_repo(tmp_path, mod):
    """A tiny tracked tree with its own manifest/deny/overlay; content
    avoids every residue class (built from plain words)."""
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    (repo / "README.md").write_text("synthetic readme\n")
    (repo / "docs" / "guide.md").write_text("synthetic guide\n")
    (repo / "SECRET.md").write_text("internal narrative\n")
    tool = repo / "tools" / "public_cut"
    (tool / "overlay").mkdir(parents=True)
    (tool / "manifest.txt").write_text("README.md\ndocs\ntools\n")
    (tool / "deny.txt").write_text("SECRET.md\n")
    (tool / "overlay" / "ATTESTATION.md").write_text("overlay attestation\n")
    _git(mod, repo, "init", "-q")
    _git(mod, repo, "symbolic-ref", "HEAD", "refs/heads/main")
    _git(mod, repo, "add", "-A")
    _, _, env = mod.release_identity()
    subprocess.run(["git", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=",
                    "commit", "-q", "-m", "synthetic"], cwd=repo, env=env,
                   check=True)
    return repo


@pytest.fixture()
def cut(tmp_path, monkeypatch):
    monkeypatch.delenv("PUBLIC_CUT_AUTHOR", raising=False)
    monkeypatch.delenv("PUBLIC_CUT_RELEASE", raising=False)
    mod = _load_tool()
    repo = _synthetic_repo(tmp_path, mod)
    tool = repo / "tools" / "public_cut"
    monkeypatch.setattr(mod, "ROOT", repo)
    monkeypatch.setattr(mod, "TOOL_DIR", tool)
    monkeypatch.setattr(mod, "MANIFEST", tool / "manifest.txt")
    monkeypatch.setattr(mod, "DENY", tool / "deny.txt")
    monkeypatch.setattr(mod, "DELETIONS", tool / "deletions.txt")
    monkeypatch.setattr(mod, "OVERLAY", tool / "overlay")
    residue = tmp_path / "residue.txt"
    residue.write_text("zzqx-synthetic-pattern\n")
    monkeypatch.setattr(mod, "RESIDUE_FILE", residue)
    monkeypatch.setattr(mod, "MIRROR_ATTESTATION", tmp_path / "absent")
    verified = []
    monkeypatch.setattr(mod, "_verify_suite", lambda d: verified.append(d))
    staging = tmp_path / "staging"  # must not exist; outside ROOT
    monkeypatch.setenv("PUBLIC_CUT_DIR", str(staging))
    return mod, repo, staging, verified


def test_happy_path_cuts_a_neutral_single_commit(cut):
    mod, repo, staging, verified = cut
    mod.main()
    assert verified == [staging]
    assert (staging / "README.md").exists() and (staging / "docs" / "guide.md").exists()
    assert (staging / "ATTESTATION.md").exists()  # the overlay landed
    assert not (staging / "SECRET.md").exists()
    assert _git(mod, staging, "rev-list", "--count", "HEAD") == "1"
    assert _git(mod, staging, "log", "-1", "--format=%an <%ae>") == mod.DEFAULT_AUTHOR


def test_dirty_tree_refuses_before_any_export(cut):
    mod, repo, staging, verified = cut
    (repo / "README.md").write_text("uncommitted edit\n")
    with pytest.raises(SystemExit, match="dirty"):
        mod.main()
    assert not staging.exists() and verified == []


def test_unclassified_path_refuses_at_pre_flight(cut):
    mod, repo, staging, verified = cut
    (repo / "orphan.md").write_text("nobody classified me\n")
    _git(mod, repo, "add", "-A")
    _, _, env = mod.release_identity()
    subprocess.run(["git", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=",
                    "commit", "-q", "-m", "orphan"], cwd=repo, env=env, check=True)
    with pytest.raises(SystemExit, match="unclassified"):
        mod.main()
    assert verified == []


def test_overlay_collision_refuses(cut):
    mod, repo, staging, verified = cut
    (mod.OVERLAY / "README.md").write_text("shadow\n")
    _commit_all(mod, repo, "overlay shadow")  # committed: past the dirty guard
    with pytest.raises(SystemExit, match="overlay would overwrite"):
        mod.main()
    assert verified == []


def test_deny_listed_file_in_staging_refuses(cut):
    mod, repo, staging, verified = cut
    staging.mkdir()  # a stray file already in the staging tree
    (staging / "SECRET.md").write_text("leaked\n")
    monkeypatch_env = os.environ.copy()
    with pytest.raises(SystemExit, match="deny-listed"):
        mod._build_and_verify(staging, mod.RESIDUE + mod.machine_patterns())
    assert verified == []


def test_red_suite_refuses_the_cut(cut, monkeypatch):
    mod, repo, staging, verified = cut

    def red(verify_dir):
        raise SystemExit("FAILED: the cut tree's suite is not green — the "
                         "mirror does not ship red")

    monkeypatch.setattr(mod, "_verify_suite", red)
    with pytest.raises(SystemExit, match="not green"):
        mod.main()


def test_release_mode_runs_the_deletion_guard(cut, monkeypatch, tmp_path):
    mod, repo, staging, verified = cut
    pub = _seed_public(mod, tmp_path)  # holds README.md + stale.txt
    monkeypatch.setenv("PUBLIC_CUT_RELEASE", str(pub))
    with pytest.raises(SystemExit, match="NOT acknowledged"):
        mod.main()
    monkeypatch.setenv("PUBLIC_CUT_DIR", str(tmp_path / "staging2"))
    mod.DELETIONS.write_text("stale.txt\n")
    _commit_all(mod, repo, "acknowledge the deletion")  # the record is committed
    import tempfile as _tf
    from pathlib import Path as _Path
    system_tmp = _Path(_tf.gettempdir())
    before = {p.name for p in system_tmp.glob("rfp-public-release-*")}
    mod.main()
    assert verified and not (verified[-1] / "stale.txt").exists()
    assert _git(mod, verified[-1], "rev-list", "--count", "HEAD") == "2"
    # M-32: the release clone lands beside the staging dir (under this
    # test's tmp_path), never as litter in the system temp root
    assert verified[-1].parent == tmp_path, verified[-1]
    after = {p.name for p in system_tmp.glob("rfp-public-release-*")}
    assert after == before, "a release clone leaked into the system temp"


def test_a_red_suite_in_the_cut_tree_names_what_failed(tmp_path, monkeypatch,
                                                       capsys):
    """P26c rider (B115 §9c): the live seam prints pytest's short test
    summary on a red run — only the last three lines survived before,
    so a red cut left no test name to chase."""
    import subprocess as _sp

    mod = _load_tool()
    verify_dir = tmp_path / "cut"
    (verify_dir / "engine").mkdir(parents=True)
    (verify_dir / "engine" / "__init__.py").write_text("")

    class _Probe:
        stdout = str(verify_dir / "engine" / "__init__.py")

    monkeypatch.setattr(mod, "run", lambda *a, **k: _Probe())
    red = _sp.CompletedProcess(
        args=[], returncode=1,
        stdout="F....\nFAILED tests/web/test_x.py::test_y - assert 1 == 2\n"
               "1 failed, 4 passed in 2.00s\n",
        stderr="a warning on stderr\n")
    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: red)
    with pytest.raises(SystemExit, match="does not ship red"):
        mod._verify_suite(verify_dir)
    out, err = capsys.readouterr()
    assert "FAILED tests/web/test_x.py::test_y - assert 1 == 2" in out
    assert "1 failed, 4 passed" in out
    assert "a warning on stderr" in err
