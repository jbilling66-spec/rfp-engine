"""P32c commit 4 — the O3 proof for replay runs: a workspace holding only
`mode: replay` runs moves no metric. The raw walk sees the runs;
production_only drops every one of them; the resolver's production
series is empty and every cost metric reads ABSENT with its reason —
never zero, never a count. And the source workspace's walk never enters
the replay directory at all."""

from engine.cli.replay import REPLAYS_DIR, run_replay
from engine.cli.slice import run_slice
from engine.evals.replay import BENCH_PURSUIT, deposit_inbox
from engine.metrics.resolver import Corpus, resolve
from engine.metrics.walker import production_only


def _quiet(*_a, **_k):
    return None


def test_replay_runs_never_enter_a_production_series(tmp_path):
    workspace = tmp_path / "ws"
    assert run_slice(workspace, out=_quiet).status == "ok"
    deposit_inbox(workspace)
    result = run_replay(workspace, BENCH_PURSUIT, out=_quiet)
    assert result.status == "ok", result.problems

    replays = Corpus(workspace / REPLAYS_DIR)
    raw = replays.runs(production=False)
    headers = [r["run"] for r in raw if r.get("record_type") == "run_start"]
    assert len(headers) == 6
    assert all(h["mode"] == "replay" and h["replay_of"] == BENCH_PURSUIT
               for h in headers)
    assert any(r.get("record_type") == "agent_call" and r.get("cost_usd", 0) > 0
               for r in raw)  # the synthetic meter ran — and must not count
    assert replays.runs() == [] and production_only(raw) == []
    assert replays.production_pursuit_ids() == set()
    for metric in ("engine_cost_per_pursuit", "engine_cost_per_section"):
        row = resolve(metric, replays)
        assert (row["status"], row["value"], row["n"]) == ("absent", None, 0)
        assert row["absent_reason"]

    # the source workspace's walk never descends into replays/
    source = Corpus(workspace)
    assert {p.pursuit_id for p in source.pursuits} == {BENCH_PURSUIT}
