"""P0-12 (P26a Group E): the extraction-gate image is pinned by digest and
runs as a non-root user — pinned as text so the next edit that drops
either is a red, not a silent widening."""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO / "docker" / "extraction-gate.Dockerfile"
MAKEFILE = REPO / "Makefile"


def test_base_image_is_digest_pinned():
    text = DOCKERFILE.read_text(encoding="utf-8")
    froms = re.findall(r"^FROM (\S+)", text, re.M)
    assert froms, "no FROM line"
    for image in froms:
        assert re.search(r"@sha256:[0-9a-f]{64}$", image), image


def test_the_gate_runs_as_a_non_root_user():
    text = DOCKERFILE.read_text(encoding="utf-8")
    users = re.findall(r"^USER (\S+)", text, re.M)
    assert users and users[-1] != "root", users
    assert text.index("USER gate") > text.index("pip install"), \
        "the dependency layers install as root; the user switch comes after"


def test_weights_verify_mounts_the_repo_read_only():
    text = MAKEFILE.read_text(encoding="utf-8")
    target = text.split("weights-verify:", 1)[1].split("\n\n", 1)[0]
    assert '/work:ro' in target
