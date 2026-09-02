"""The assistant lane's self-report (P14/C11, B64).

The lane writes proper run logs that no metric reads — deliberately, so
support spend never pools into a pursuit cost series. These tests pin
BOTH halves: the lane reports on itself honestly, AND it stays invisible
to the pursuit walker."""

import json

import pytest
from fastapi.testclient import TestClient

from engine.assistant.loop import run_turn
from engine.assistant.session import SESSION_CEILING_USD, AssistantSession
from engine.assistant.usage import lane_usage
from engine.llm.caller import FakeCaller
from engine.metrics.resolver import Corpus
from engine.version import engine_version
from engine.web.server import create_app
from tests.assistant.conftest import FIXED_AT, build_store
from tests.web.conftest import raising_caller, sign_in


def _script(prompt: str) -> str:
    if "[TOOL_RESULT" in prompt:
        return json.dumps({"action": "answer",
                           "text": "Hypercare runs two weeks.",
                           "citations": ["kb_hyper0001"]})
    return json.dumps({"action": "tool", "tool": "open_card",
                       "args": {"kb_id": "kb_hyper0001"}})


def _one_session(workspace, store, script=_script, message="hypercare?"):
    session = AssistantSession.mint(
        workspace, mode="dry_run", engine_version=engine_version(),
        config={"suite": "assistant-tests"}, kb_snapshot=store.snapshot())
    run_turn(session, FakeCaller({"steward_assistant": script}),
             store=store, workspace=workspace,
             records_provider=lambda: [], message=message,
             who="Sam Steward", at=FIXED_AT)
    return session


# ------------------------------------------------------------ the reader

def test_none_before_first_use_never_a_fabricated_zero(workspace):
    """SupportTrace's honesty rule, inherited: a lane nobody has used has
    no numbers — which is not the same as a lane that cost nothing."""
    assert lane_usage(workspace) is None


def test_usage_aggregates_the_lanes_own_records(workspace, store):
    _one_session(workspace, store)
    usage = lane_usage(workspace)

    assert usage["session_count"] == 1
    assert usage["calls"] == 2          # tool turn + answer turn
    assert usage["cost_usd"] > 0
    assert usage["tools"] == {"open_card": 1}
    assert usage["cited_answers"] == 1
    assert usage["injection_flags"] == 0
    assert usage["tool_refusals"] == 0
    assert usage["ceiling_usd"] == SESSION_CEILING_USD
    assert usage["cost_source"] == "assistant_lane"

    row = usage["sessions"][0]
    assert row["calls"] == 2
    assert row["over_ceiling"] is False
    assert row["cost_usd"] == pytest.approx(usage["cost_usd"])


def test_usage_counts_refusals_flags_and_declines(workspace, store):
    """A refused tool, a decline, and a screen flag all reach the report
    — they are the signals a steward actually acts on."""
    def refuse_then_decline(prompt):
        if "[TOOL_ERROR" in prompt:
            return json.dumps({"action": "decline",
                               "topic": "restricted engagement detail"})
        return json.dumps({"action": "tool", "tool": "open_card",
                           "args": {"kb_id": "kb_restr0001"}})

    _one_session(workspace, store, script=refuse_then_decline)
    usage = lane_usage(workspace)
    assert usage["tool_refusals"] == 1
    assert usage["declines"] == [
        {"topic": "restricted engagement detail", "count": 1}]
    assert usage["cited_answers"] == 0


def test_usage_spans_multiple_sessions(workspace, store):
    _one_session(workspace, store)
    _one_session(workspace, store, message="again?")
    usage = lane_usage(workspace)
    assert usage["session_count"] == 2
    assert usage["calls"] == 4
    assert usage["tools"] == {"open_card": 2}
    assert len({s["session_id"] for s in usage["sessions"]}) == 2


def test_lane_stays_invisible_to_pursuit_metrics(workspace, store):
    """The other half of the contract: reporting on the lane must NOT
    make its spend visible to the pursuit corpus (B36(2))."""
    _one_session(workspace, store)
    corpus = Corpus(workspace)
    assert corpus.pursuits == []
    assert corpus.runs() == []
    assert lane_usage(workspace)["calls"] == 2


# ------------------------------------------------------------ the route

@pytest.fixture
def client(tmp_path):
    ws = tmp_path / "ws"
    build_store(ws)
    app = create_app(ws, make_caller=raising_caller, now=lambda: FIXED_AT)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        sign_in(client, "Sam Steward")
        yield client


def test_usage_route_notes_the_empty_lane(client):
    body = client.get("/api/assistant/usage").json()
    assert body["note"] == "no assistant sessions yet"
    assert body["ceiling_usd"] == SESSION_CEILING_USD


def test_usage_route_reports_after_a_turn(client):
    client.app.state.assistant_caller = FakeCaller(
        {"steward_assistant": _script})
    sid = client.post("/api/assistant/session").json()["session_id"]
    client.post(f"/api/assistant/session/{sid}/message",
                json={"message": "hypercare?"})
    body = client.get("/api/assistant/usage").json()
    assert body["session_count"] == 1
    assert body["sessions"][0]["session_id"] == sid
    assert body["tools"] == {"open_card": 1}


def test_usage_route_is_operator_gated(client):
    assert TestClient(client.app, base_url="http://127.0.0.1").get(
        "/api/assistant/usage").status_code == 401
