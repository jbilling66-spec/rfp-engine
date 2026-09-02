"""KB CLI subcommands drive the same engine paths the tests prove — and the
seed run's log passes the check-run validator (line-valid, gapless), the
CLI form of the run-log acceptance clause.
"""

from engine.cli.main import main


def test_kb_seed_then_check_run(tmp_path, capsys):
    kb = tmp_path / "kb"
    assert main(["kb", "seed", "--kb", str(kb)]) == 0
    out = capsys.readouterr().out
    assert "snapshot: kb@" in out
    assert main(["check-run", str(kb / "runs" / "run_0001" / "run.jsonl")]) == 0
    assert "seq gapless" in capsys.readouterr().out


def test_kb_search_and_open_on_committed_store(capsys):
    assert main(["kb", "search", "payroll parallel testing for a utility"]) == 0
    out = capsys.readouterr().out.strip().splitlines()
    assert out and out[0].startswith("kb_")
    kb_id = out[0].split()[0]
    assert main(["kb", "open", kb_id]) == 0
    assert capsys.readouterr().out.strip()


def test_kb_snapshot_on_committed_store(capsys):
    assert main(["kb", "snapshot"]) == 0
    assert capsys.readouterr().out.startswith("kb@")


def test_kb_purge_on_scratch_copy(tmp_path, capsys):
    kb = tmp_path / "kb"
    assert main(["kb", "seed", "--kb", str(kb)]) == 0
    capsys.readouterr()
    assert main(["kb", "purge", "--kb", str(kb), "--client",
                 "Tallgrass County Schools", "--actor", "owner"]) == 0
    out = capsys.readouterr().out
    assert "CLEAN" in out


def test_kb_where_used_denied_for_unknown_actor(tmp_path, capsys):
    kb = tmp_path / "kb"
    assert main(["kb", "seed", "--kb", str(kb)]) == 0
    capsys.readouterr()
    assert main(["kb", "where-used", "Aaron Tuck", "--kb", str(kb),
                 "--actor", "mallory"]) == 1
    assert main(["kb", "where-used", "Aaron Tuck", "--kb", str(kb),
                 "--actor", "owner"]) == 0
    assert "kb_" in capsys.readouterr().out



def test_kb_cli_runs_mint_through_the_one_mint(tmp_path):
    """P25 item 3: the KB store's run ids come from the shared mint — a
    deleted middle run never recycles an id (the CLI used to count)."""
    import types

    from engine.cli.kb import _new_log
    store = types.SimpleNamespace(root=tmp_path / "kb")
    for name in ("run_0001", "run_0002", "run_0003"):
        (store.root / "runs" / name).mkdir(parents=True)
    (store.root / "runs" / "run_0002").rmdir()
    log = _new_log(store)
    assert log.run_id == "run_0004"
