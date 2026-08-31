"""Sandbox containment proofs (C2, B51) — offline, always-run.

The runner takes any dotted target, so none of this needs docling: each
test is a guard firing on a child that misbehaves the way a hostile
document makes a parser misbehave, plus the benign twin proving the
happy path round-trips.
"""

from __future__ import annotations

import os

from engine.extraction.sandbox import run_sandboxed

_T = "tests.extraction.sandbox_targets:{}"


def test_benign_target_round_trips(tmp_path):
    res = run_sandboxed(
        _T.format("echo"), {"x": 42}, timeout_s=30, mem_mb=512, workdir=tmp_path
    )
    assert res.status == "ok"
    assert res.result == {"echo": 42}
    assert res.error is None
    assert res.peak_rss_bytes and res.peak_rss_bytes > 0
    assert list(tmp_path.iterdir()) == []  # workdir left as the target left it


def test_malformed_input_kills_the_parse_and_nothing_else(tmp_path):
    """The acceptance clause, verbatim: a malformed PDF must be able to
    kill the parse and nothing else (spec §A3). SIGABRT mid-parse — no
    exception path, no result file — and the parent survives with a
    structured failure and an untouched workdir."""
    res = run_sandboxed(
        _T.format("die_hard"), {}, timeout_s=30, mem_mb=512, workdir=tmp_path
    )
    assert res.status == "failed"
    assert res.result is None
    assert "child died without a result" in res.error
    assert list(tmp_path.iterdir()) == []


def test_wall_clock_timeout_kills_the_child(tmp_path):
    res = run_sandboxed(
        _T.format("sleep_forever"), {}, timeout_s=1, mem_mb=512, workdir=tmp_path
    )
    assert res.status == "timeout"
    assert res.duration_ms < 10_000  # killed at ~1s, not at the target's 60


def test_network_egress_denied_in_child(tmp_path):
    res = run_sandboxed(
        _T.format("probe_network"), {}, timeout_s=30, mem_mb=512, workdir=tmp_path
    )
    assert res.status == "ok"
    assert res.result["raised"] == "SandboxNetworkDenied"


def test_dns_denied_in_child(tmp_path):
    res = run_sandboxed(
        _T.format("probe_dns"), {}, timeout_s=30, mem_mb=512, workdir=tmp_path
    )
    assert res.status == "ok"
    assert res.result["raised"] == "SandboxNetworkDenied"


def test_jail_shape_matches_the_contract(tmp_path):
    """cwd is the workdir, the offline env is set, and the memory ceiling
    is applied where the platform enforces it (Linux — the gate container
    and A5; macOS records the attempt, a branch, not a skip)."""
    res = run_sandboxed(
        _T.format("report_jail"), {}, timeout_s=30, mem_mb=256, workdir=tmp_path
    )
    assert res.status == "ok"
    jail = res.result
    assert jail["cwd"] == str(tmp_path.resolve())
    assert jail["hf_hub_offline"] == "1"
    if jail["platform"] == "linux":
        assert jail["rlimit_as"] == 256 * 1024 * 1024
    else:
        assert jail["rlimit_as"] in (256 * 1024 * 1024, resource_unlimited())


def test_relative_writes_land_in_the_jail(tmp_path):
    res = run_sandboxed(
        _T.format("write_relative"), {}, timeout_s=30, mem_mb=512, workdir=tmp_path
    )
    assert res.status == "ok"
    assert (tmp_path / "parse-output.txt").exists()
    assert not os.path.exists("parse-output.txt")  # nothing in the parent's cwd


def resource_unlimited() -> int:
    import resource

    return resource.RLIM_INFINITY
