"""The one run-id mint (P25 item 3, P0-3): max(existing)+1 over real run
ids — a deleted middle run never recycles an id, a stray entry is never
counted, and the latest id is the numeric max past four digits."""

from engine.workspace import PursuitDir
from engine.workspace.pursuit import RUN_ID, latest_run_id_in, mint_run_id


def test_mint_is_max_plus_one_never_a_count(tmp_path):
    pursuit = PursuitDir(tmp_path, "pur_t")
    runs = pursuit.root / "runs"
    for name in ("run_0001", "run_0002", "run_0003"):
        (runs / name).mkdir()
    (runs / "run_0002").rmdir()  # a "cleanup" of a middle run
    assert pursuit.new_run_id() == "run_0004"  # never run_0003 again
    (runs / ".DS_Store").write_text("")
    (runs / "notes").mkdir()
    assert pursuit.new_run_id() == "run_0004"  # strays are not counted
    assert pursuit.latest_run_id() == "run_0003"


def test_latest_is_numeric_past_four_digits(tmp_path):
    runs = tmp_path / "runs"
    for name in ("run_0009", "run_9999", "run_10000"):
        (runs / name).mkdir(parents=True)
    assert latest_run_id_in(runs) == "run_10000"  # lexical would say 9999
    assert mint_run_id(runs) == "run_10001"
    assert mint_run_id(tmp_path / "absent") == "run_0001"
    assert RUN_ID.fullmatch("run_0001") and not RUN_ID.fullmatch("run_1")
