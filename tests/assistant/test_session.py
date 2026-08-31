"""Sessions: the unmixable lane, the traversal guard, derived spend."""

import json

import pytest

from engine.assistant.session import AssistantSession, UnknownSession
from engine.metrics.walker import is_pursuit_dir
from engine.version import engine_version


def _mint(workspace):
    return AssistantSession.mint(
        workspace, mode="dry_run", engine_version=engine_version(),
        config={"suite": "assistant-tests"}, kb_snapshot="kb@empty")


def test_assistant_lane_invisible_to_pursuit_walker(workspace):
    """The D21 unmixability property, inherited by location: nothing
    under support/ reads as a pursuit, so assistant spend can never pool
    into pursuit cost aggregates."""
    session = _mint(workspace)
    assert session.logger.path.exists()
    assert not is_pursuit_dir(workspace / "support")
    assert not is_pursuit_dir(workspace / "support" / "assistant")
    assert not is_pursuit_dir(session.run_dir)


def test_session_is_a_run_and_resumes_gapless(workspace):
    session = _mint(workspace)
    first_seq = session.logger._seq
    reopened = AssistantSession.load(workspace, session.session_id)
    assert reopened.logger._seq == first_seq  # resumed, not restarted


def test_unknown_and_hostile_session_ids_refused(workspace):
    with pytest.raises(UnknownSession):
        AssistantSession.load(workspace, "sas_00000000")
    for hostile in ("../../etc", "sas_../x", "", "sas_UPPER123",
                    "run_0001"):
        with pytest.raises(UnknownSession):
            AssistantSession.load(workspace, hostile)


def test_spent_usd_derives_from_agent_call_lines(workspace):
    session = _mint(workspace)
    assert session.spent_usd() == 0.0
    session.logger.emit(
        "agent_call", stage="assistant", agent="steward_assistant",
        model="fake-mid-1", cost_usd=1.25,
        tokens={"input": 100, "output": 50})
    session.logger.emit(
        "agent_call", stage="assistant", agent="steward_assistant",
        model="fake-mid-1", cost_usd=0.5,
        tokens={"input": 10, "output": 5})
    assert session.spent_usd() == 1.75


def test_transcript_earned_sets_rebuild(workspace):
    session = _mint(workspace)
    session.append({"type": "assistant", "n": 1, "text": "t",
                    "citations": ["a.md"], "earned_docs": ["a.md"],
                    "earned_cards": ["kb_x"], "earned_proposals": []})
    docs, cards, proposals = session.earned()
    assert docs == {"a.md"} and cards == {"kb_x"} and proposals == set()
