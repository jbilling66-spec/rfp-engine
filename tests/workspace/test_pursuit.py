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


def test_file_sha256_missing_is_none_and_matches_hashlib(tmp_path):
    """The one digest (P25 C0): every hash binding in the engine computes
    through this helper, so its two properties are the contract — a
    missing file is None (never an exception), a present file's digest
    is exactly sha256 over its bytes."""
    import hashlib
    pursuit = PursuitDir(tmp_path, "pur_t")
    assert pursuit.file_sha256("plan.frozen.json") is None
    pursuit.write_artifact("bid_brief", VALID_BRIEF)
    expected = hashlib.sha256(
        (pursuit.root / "brief.json").read_bytes()).hexdigest()
    assert pursuit.file_sha256("brief.json") == expected
    assert len(expected) == 64


def test_checkpoints_and_run_ids(tmp_path):
    pursuit = PursuitDir(tmp_path, "pur_t")
    assert pursuit.completed_stages() == set()
    pursuit.checkpoint("intake", {"n": 1})
    assert pursuit.completed_stages() == {"intake"}
    assert pursuit.checkpoint_payload("intake") == {"n": 1}
    assert pursuit.new_run_id() == "run_0001"
    assert pursuit.latest_run_id() is None


# --- the freeze door (P25 item 5, register P0-2) -------------------------

def test_write_artifact_and_write_json_refuse_frozen_names(tmp_path):
    """The seam has no in-place path to a freeze: both writers refuse a
    `*.frozen.json` name, and nothing lands."""
    pursuit = PursuitDir(tmp_path, "pur_t")
    with pytest.raises(ContractError, match="freeze_artifact"):
        pursuit.write_artifact("bid_brief", VALID_BRIEF,
                               name="brief.frozen.json")
    with pytest.raises(ContractError, match="freeze_artifact"):
        pursuit.write_json("plan.frozen.json", {"status": "approved"})
    assert not (pursuit.root / "brief.frozen.json").exists()
    assert not (pursuit.root / "plan.frozen.json").exists()


def test_write_and_read_refuse_paths_escaping_the_pursuit_root(tmp_path):
    pursuit = PursuitDir(tmp_path, "pur_t")
    for name in ("../other/brief.json", "../../x.json", "/tmp/x.json"):
        with pytest.raises(ContractError, match="escapes"):
            pursuit.write_json(name, {"n": 1})
        with pytest.raises(ContractError, match="escapes"):
            pursuit.read_artifact(name)
    assert not (tmp_path / "other").exists()


def test_freeze_artifact_is_idempotent_on_equal_bytes_and_refuses_on_different(
        tmp_path):
    """The replay contract for item 1 (a crash-after-freeze resubmit
    converges) and the tamper contract for item 5 (a different freeze
    never overwrites), in one door."""
    import hashlib
    pursuit = PursuitDir(tmp_path, "pur_t")
    path, sha = pursuit.freeze_artifact("bid_brief", VALID_BRIEF)
    assert path == pursuit.root / "brief.frozen.json"
    assert sha == hashlib.sha256(path.read_bytes()).hexdigest()
    before = path.stat().st_mtime_ns
    again, sha2 = pursuit.freeze_artifact("bid_brief", dict(VALID_BRIEF))
    assert (again, sha2) == (path, sha)
    assert path.stat().st_mtime_ns == before  # returned, not rewritten
    changed = {**VALID_BRIEF, "status": "approved"}
    with pytest.raises(ContractError, match="never rewritten"):
        pursuit.freeze_artifact("bid_brief", changed)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == sha
    # the door validates like every artifact writer
    with pytest.raises(ContractError):
        pursuit.freeze_artifact("bid_brief", {"pursuit_id": "pur_t"})


def test_archive_frozen_moves_intact_and_returns_sha(tmp_path):
    pursuit = PursuitDir(tmp_path, "pur_t")
    path, sha = pursuit.freeze_artifact("bid_brief", VALID_BRIEF)
    moved = pursuit.archive_frozen("bid_brief", "addenda/addm_01/brief.frozen.superseded.json")
    assert moved == sha
    assert not path.exists()
    archived = pursuit.root / "addenda" / "addm_01" / "brief.frozen.superseded.json"
    assert archived.exists()
    import hashlib
    assert hashlib.sha256(archived.read_bytes()).hexdigest() == sha
    with pytest.raises(FileNotFoundError):
        pursuit.archive_frozen("bid_brief", "addenda/addm_02/x.json")
    pursuit.freeze_artifact("bid_brief", VALID_BRIEF)
    with pytest.raises(ContractError, match="never overwritten"):
        pursuit.archive_frozen("bid_brief", "addenda/addm_01/brief.frozen.superseded.json")
    with pytest.raises(ContractError, match="escapes"):
        pursuit.archive_frozen("bid_brief", "../escape.json")


def test_read_frozen_refuses_missing_checkpoint_missing_sha_and_mismatch(
        tmp_path):
    """Three refusal shapes, all distinct from FileNotFoundError: no gate
    checkpoint vouches; the checkpoint carries no frozen_sha256; the
    recorded sha differs from the bytes on disk. The fourth arm is the
    happy path: file and checkpoint agree, the dict comes back."""
    pursuit = PursuitDir(tmp_path, "pur_t")
    with pytest.raises(FileNotFoundError):
        pursuit.read_frozen("bid_brief")
    path, sha = pursuit.freeze_artifact("bid_brief", VALID_BRIEF)
    with pytest.raises(ContractError, match="no gate_1 checkpoint"):
        pursuit.read_frozen("bid_brief")
    pursuit.checkpoint("gate_1", {"decision": "approved", "actor": "a",
                                  "at": "2026-08-09T09:00:00"})
    with pytest.raises(ContractError, match="frozen_sha256 absent"):
        pursuit.read_frozen("bid_brief")
    pursuit.checkpoint("gate_1", {"decision": "approved", "actor": "a",
                                  "at": "2026-08-09T09:00:00",
                                  "frozen_sha256": "0" * 64})
    with pytest.raises(ContractError, match="fails verification"):
        pursuit.read_frozen("bid_brief")
    pursuit.checkpoint("gate_1", {"decision": "approved", "actor": "a",
                                  "at": "2026-08-09T09:00:00",
                                  "frozen_sha256": sha})
    assert pursuit.read_frozen("bid_brief") == VALID_BRIEF
    # a byte changed after the gate, through a raw write past the door
    path.write_text(path.read_text().replace("Northwind", "Southwind"))
    with pytest.raises(ContractError, match="modified after the gate"):
        pursuit.read_frozen("bid_brief")


# --- the stamp digest field (P25 C3, schema commit) ----------------------

def test_stamp_blocks_accept_an_optional_request_sha256(tmp_path):
    """gate0/gate1 (brief) and gate2 (plan) stamp blocks accept the
    optional digest; a malformed digest is refused; a stamp WITHOUT it
    is still valid (pre-P25 workspaces keep validating)."""
    pursuit = PursuitDir(tmp_path, "pur_t")
    digest = "ab" * 32
    stamped = {**VALID_BRIEF, "status": "approved",
               "gate0": {"approved_by": "a", "at": "2026-08-09T09:00:00",
                         "request_sha256": digest},
               "gate1": {"approved_by": "a", "at": "2026-08-09T09:00:00",
                         "request_sha256": digest}}
    pursuit.write_artifact("bid_brief", stamped)
    pursuit.write_artifact("bid_brief", {**VALID_BRIEF, "status": "approved",
                                         "gate1": {"approved_by": "a",
                                                   "at": "2026-08-09T09:00:00"}})
    with pytest.raises(ContractError):
        pursuit.write_artifact("bid_brief", {
            **stamped, "gate1": {**stamped["gate1"], "request_sha256": "nope"}})
    plan = {"pursuit_id": "pur_t", "path": "A_designated", "sections": [],
            "status": "approved",
            "gate2": {"approved_by": "a", "at": "2026-08-09T09:00:00",
                      "request_sha256": digest}}
    pursuit.write_artifact("pursuit_plan", plan)
    with pytest.raises(ContractError):
        pursuit.write_artifact("pursuit_plan", {
            **plan, "gate2": {**plan["gate2"], "request_sha256": "X" * 64}})
