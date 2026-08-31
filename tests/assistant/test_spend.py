"""The per-session ceiling aborts loudly (P14 row) — the N6 discipline
carried across HTTP turns by pre-seeding TracedCaller with the
session's own derived spend."""

import json

import pytest

from engine.assistant.loop import run_turn
from engine.assistant.session import SESSION_CEILING_USD, AssistantSession
from engine.llm.caller import CostCeilingExceeded, FakeCaller
from engine.runlog.writer import read_run
from engine.version import engine_version
from tests.assistant.conftest import FIXED_AT


def test_session_ceiling_aborts_loudly(workspace, store):
    session = AssistantSession.mint(
        workspace, mode="dry_run", engine_version=engine_version(),
        config={"suite": "assistant-tests"}, kb_snapshot=store.snapshot())
    # A prior expensive turn, on the record the ceiling derives from.
    session.logger.emit(
        "agent_call", stage="assistant", agent="steward_assistant",
        model="fake-mid-1", cost_usd=SESSION_CEILING_USD + 0.01,
        tokens={"input": 1, "output": 1})
    assert session.spent_usd() > SESSION_CEILING_USD

    def answer(prompt):
        return json.dumps({"action": "decline", "topic": "anything"})

    with pytest.raises(CostCeilingExceeded):
        run_turn(session, FakeCaller({"steward_assistant": answer}),
                 store=store, workspace=workspace,
                 records_provider=lambda: [], message="hello?",
                 who="Sam Steward", at=FIXED_AT)
    records = read_run(session.logger.path)
    ceiling_lines = [r for r in records if r["record_type"] == "error"
                     and r["error"]["code"] == "cost_ceiling"]
    assert ceiling_lines, "the abort must be on the record"
    assert ceiling_lines[-1]["error"]["action_taken"] == "aborted_run"
