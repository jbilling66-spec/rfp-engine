"""P2-62 (P29b b4): the runbook promised that an unreadable
`drafts/annotated-draft.json` is rebuilt by the next Advance — the board
half was true, the recovery half raised `JSONDecodeError` out of the
driver (the job lane's `error`), so the pursuit was wedged until someone
hand-deleted a file the runbook said never needs deleting. Now: the
unreadable bytes are archived aside (`.corrupt-NNN`, nothing destroyed),
validation re-runs, the run log names the repair. The draft itself
holds the review rounds' human edits and is NEVER rebuilt: an
unreadable draft is a typed refusal naming the file and the runbook."""

import pytest

from engine.contracts import ContractError
from engine.llm import FakeCaller, TracedCaller
from engine.pipeline.driver import advance, draft_is_current, validation_is_current
from engine.runlog import read_run
from engine.web.state import board
from tests.revision.fixtures.rounds import round_script, validated_pursuit

AT = "2026-09-11T09:00:00"
TORN = b'{"draft_sha256": "abc", "plan_sha'


def _staged(tmp_path):
    """The P8 fixture chain's validated pursuit — every stage current, so
    an Advance has exactly one thing to do once the annotated draft is
    torn (the lessons.md crash-staging rule: the state built, not
    reconstructed by deleting artifacts after a run)."""
    pursuit = validated_pursuit(tmp_path)
    pursuit.checkpoint("gate_0", {"decision": "approved"})
    assert draft_is_current(pursuit) and validation_is_current(pursuit)
    return tmp_path, pursuit


def _advance(ws, pursuit):
    return advance(pursuit, mode="dry_run", kb_root=ws / "kb", at=AT,
                   make_caller=lambda log: TracedCaller(
                       FakeCaller(round_script()), log))


def _row(ws, pursuit):
    return next(r for r in board(ws) if r["pursuit_id"] == pursuit.pursuit_id)


def test_an_unreadable_annotated_draft_is_archived_aside_and_rebuilt(
        tmp_path):
    ws, pursuit = _staged(tmp_path)
    torn = pursuit.root / "drafts" / "annotated-draft.json"
    torn.write_bytes(TORN)
    row = _row(ws, pursuit)
    assert row["stage"] == "corrupt" and any(
        c.startswith("annotated-draft.json") for c in row["corrupt"])
    result = _advance(ws, pursuit)
    assert result.status == "ok" and result.ran_stages == ["validation"], \
        result
    assert validation_is_current(pursuit) is True  # rebuilt, well-formed
    archived = pursuit.root / "drafts" / "annotated-draft.json.corrupt-001"
    assert archived.read_bytes() == TORN  # nothing destroyed
    run_files = sorted((pursuit.root / "runs").glob("*/run.jsonl"))
    records = read_run(run_files[-1])
    repair = next(r for r in records if r["record_type"] == "error")
    assert repair["error"]["code"] == "annotated_draft_unreadable"
    assert "corrupt-001" in repair["error"]["message"]
    assert repair["error"]["recoverable"] is True
    assert "corrupt" not in _row(ws, pursuit)


def test_a_second_corruption_archives_beside_the_first(tmp_path):
    ws, pursuit = _staged(tmp_path)
    torn = pursuit.root / "drafts" / "annotated-draft.json"
    torn.write_bytes(TORN)
    _advance(ws, pursuit)
    torn.write_bytes(TORN + b"again")
    notices = []
    assert validation_is_current(pursuit, notices=notices) is False
    assert notices[0][0] == "annotated_draft_unreadable"
    assert (pursuit.root / "drafts"
            / "annotated-draft.json.corrupt-002").read_bytes() == TORN + b"again"


def test_an_unreadable_draft_is_a_typed_refusal_never_a_rewrite(tmp_path):
    ws, pursuit = _staged(tmp_path)
    draft = pursuit.root / "drafts" / "draft.json"
    draft.write_bytes(TORN)
    with pytest.raises(ContractError, match="recovery runbook"):
        draft_is_current(pursuit)
    with pytest.raises(ContractError, match="draft.json unreadable"):
        _advance(ws, pursuit)
    assert draft.read_bytes() == TORN  # untouched, unarchived
    assert not list((pursuit.root / "drafts").glob("*.corrupt-*"))
