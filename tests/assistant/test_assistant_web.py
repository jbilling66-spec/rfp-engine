"""The /api/assistant routes — the test_advisor.py shape on the new
surface: operator-gated, seam-injected, typed refusals, no phantom
state."""

import json

import pytest
from fastapi.testclient import TestClient

from engine.assistant.session import SESSION_CEILING_USD, AssistantSession
from engine.llm.caller import FakeCaller
from engine.web.server import create_app
from tests.assistant.conftest import build_store
from tests.web.conftest import FIXED_AT, raising_caller, sign_in


def _script(prompt: str) -> str:
    if "[TOOL_RESULT" in prompt:
        return json.dumps({"action": "answer",
                           "text": "Hypercare runs two weeks.",
                           "citations": ["kb_hyper0001"]})
    return json.dumps({"action": "tool", "tool": "open_card",
                       "args": {"kb_id": "kb_hyper0001"}})


@pytest.fixture
def client(tmp_path):
    workspace = tmp_path / "ws"
    build_store(workspace)
    app = create_app(workspace, make_caller=raising_caller,
                     now=lambda: FIXED_AT)
    with TestClient(app) as client:
        sign_in(client, "Sam Steward")
        yield client


def _mint(client):
    return client.post("/api/assistant/session").json()["session_id"]


def test_mint_message_and_transcript_roundtrip(client):
    client.app.state.assistant_caller = FakeCaller(
        {"steward_assistant": _script})
    minted = client.post("/api/assistant/session").json()
    assert minted["ceiling_usd"] == SESSION_CEILING_USD
    assert minted["spent_usd"] == 0.0
    sid = minted["session_id"]

    out = client.post(f"/api/assistant/session/{sid}/message",
                      json={"message": "How is hypercare covered?"}).json()
    assert out["reply"]["action"] == "answer"
    assert out["reply"]["citations"] == ["kb_hyper0001"]
    assert out["tool_trail"] == [{"tool": "open_card", "status": "ok"}]
    assert out["screen_flags"] == []
    assert 0 < out["spent_usd"] < SESSION_CEILING_USD

    read = client.get(f"/api/assistant/session/{sid}").json()
    kinds = [r["type"] for r in read["transcript"]]
    assert kinds[0] == "user" and kinds[-1] == "assistant"


def test_guests_and_anonymous_refused(client):
    """P14 row: share-link guests refused — assistant routes demand the
    operator cookie a guest lane never issues."""
    bare = TestClient(client.app)
    assert bare.post("/api/assistant/session").status_code == 401
    assert bare.get("/api/assistant/session/sas_00000000").status_code == 401
    assert bare.post("/api/assistant/session/sas_00000000/message",
                     json={"message": "hi"}).status_code == 401


def test_unknown_session_is_404_and_creates_nothing(client):
    workspace = client.app.state.workspace
    assert client.get(
        "/api/assistant/session/sas_deadbeef").status_code == 404
    response = client.post("/api/assistant/session/sas_deadbeef/message",
                           json={"message": "hello"})
    assert response.status_code == 404
    assert not (workspace / "support" / "assistant" / "runs"
                / "sas_deadbeef").exists()


def test_message_length_gated(client):
    sid = _mint(client)
    assert client.post(f"/api/assistant/session/{sid}/message",
                       json={"message": ""}).status_code == 422
    assert client.post(f"/api/assistant/session/{sid}/message",
                       json={"message": "x" * 5000}).status_code == 422


def test_malformed_wire_is_502_and_still_recorded(client):
    """The unscripted zero-spend default produces a non-JSON reply — the
    502 is typed, and the failure is on the session's own run log."""
    sid = _mint(client)
    response = client.post(f"/api/assistant/session/{sid}/message",
                           json={"message": "hello there"})
    assert response.status_code == 502
    assert "assistant wire refused" in response.json()["detail"]
    workspace = client.app.state.workspace
    log = (workspace / "support" / "assistant" / "runs" / sid
           / "run.jsonl")
    records = [json.loads(line) for line in
               log.read_text(encoding="utf-8").splitlines()]
    assert records[-1]["error"]["code"] == "assistant_wire"
    assert any(r["record_type"] == "agent_call" for r in records)


def test_ceiling_preflight_402_before_any_call(client):
    """P14 row: the ceiling aborts loudly — and pre-flight means a spent
    session refuses BEFORE the model is asked (the caller here raises if
    ever touched)."""

    class _Touched(Exception):
        pass

    class _NeverCalled:
        def call_for(self, *a, **k):
            raise _Touched()

    client.app.state.assistant_caller = _NeverCalled()
    sid = _mint(client)
    workspace = client.app.state.workspace
    session = AssistantSession.load(workspace, sid)
    session.logger.emit(
        "agent_call", stage="assistant", agent="steward_assistant",
        model="fake-mid-1", cost_usd=SESSION_CEILING_USD + 0.01,
        tokens={"input": 1, "output": 1})
    response = client.post(f"/api/assistant/session/{sid}/message",
                           json={"message": "one more thing"})
    assert response.status_code == 402
    assert "ceiling" in response.json()["detail"]
