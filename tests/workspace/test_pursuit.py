"""Workspace: artifacts validate before landing (an invalid bid-brief is
rejected — P0 acceptance), writes are atomic, checkpoints drive resume."""

import pytest

from engine.contracts import ContractError
from engine.workspace import PursuitDir

VALID_BRIEF = {
    "pursuit_id": "pur_t",
    "buyer": {"name": "Synthetic Northwind Health"},
    "procurement": {},
    "requirements_matrix": [{"requirement": "Describe your implementation methodology."}],
    "status": "draft",
}


def test_valid_brief_lands_and_reads_back(tmp_path):
    pursuit = PursuitDir(tmp_path, "pur_t")
    pursuit.write_artifact("bid_brief", VALID_BRIEF)
    assert pursuit.read_artifact("brief.json")["buyer"]["name"] == "Synthetic Northwind Health"


def test_invalid_brief_is_rejected_and_nothing_lands(tmp_path):
    pursuit = PursuitDir(tmp_path, "pur_t")
    invalid = {k: v for k, v in VALID_BRIEF.items() if k != "buyer"}
    with pytest.raises(ContractError):
        pursuit.write_artifact("bid_brief", invalid)
    assert not (pursuit.root / "brief.json").exists()


def test_checkpoints_and_run_ids(tmp_path):
    pursuit = PursuitDir(tmp_path, "pur_t")
    assert pursuit.completed_stages() == set()
    pursuit.checkpoint("intake", {"n": 1})
    assert pursuit.completed_stages() == {"intake"}
    assert pursuit.checkpoint_payload("intake") == {"n": 1}
    assert pursuit.new_run_id() == "run_0001"
    assert pursuit.latest_run_id() is None
