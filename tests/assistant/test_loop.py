"""The turn loop: every action on the run log, deterministic scripted
transcripts, typed refusals for exhaustion / malformed wire / un-earned
citations."""

import json

import pytest

from engine.assistant.loop import run_turn
from engine.assistant.session import AssistantSession
from engine.assistant.wire import AssistantWireError
from engine.llm.caller import FakeCaller
from engine.runlog.writer import assert_seq_gapless, read_run
from engine.version import engine_version
from tests.assistant.conftest import FIXED_AT, build_store


def _mint(workspace, store):
    return AssistantSession.mint(
        workspace, mode="dry_run", engine_version=engine_version(),
        config={"suite": "assistant-tests"}, kb_snapshot=store.snapshot())


def _turn(session, script, store, workspace, message="How is hypercare "
          "covered, and what does the runbook say about re-ingest?"):
    return run_turn(
        session, FakeCaller({"steward_assistant": script}), store=store,
        workspace=workspace, records_provider=lambda: [],
        message=message, who="Sam Steward", at=FIXED_AT)


def three_step_script(prompt: str) -> str:
    """The house state-machine idiom: branch on how many results the
    rendered transcript already carries."""
    seen = prompt.count("[TOOL_RESULT")
    if seen == 0:
        return json.dumps({"action": "tool", "tool": "read_doc",
                           "args": {"name": "steward-runbook.md"}})
    if seen == 1:
        return json.dumps({"action": "tool", "tool": "card_search",
                           "args": {"query": "hypercare"}})
    if seen == 2:
        return json.dumps({"action": "tool", "tool": "open_card",
                           "args": {"kb_id": "kb_hyper0001"}})
    return json.dumps({
        "action": "answer",
        "text": "Hypercare runs two weeks; the runbook covers re-ingest "
                "reconciliation.",
        "citations": ["steward-runbook.md", "kb_hyper0001"]})


def test_every_tool_call_lands_on_the_run_log(workspace, store):
    """P14 row: every tool call on the run log — one tool_call line per
    action with args+result digests, retrieval tools also carrying their
    own kb_retrieval lines, the final answer carrying its cite line, and
    seq gapless end to end."""
    session = _mint(workspace, store)
    result = _turn(session, three_step_script, store, workspace)
    assert result.reply["action"] == "answer"
    assert [t["tool"] for t in result.tool_trail] == \
        ["read_doc", "card_search", "open_card"]

    records = read_run(session.logger.path)
    assert_seq_gapless(records)
    tool_lines = [r for r in records if r["record_type"] == "tool_call"]
    assert [r["tool"] for r in tool_lines] == \
        ["read_doc", "card_search", "open_card"]
    for line in tool_lines:
        assert line["stage"] == "assistant"
        assert line["tool_args_digest"].startswith("sha256:")
        assert line["tool_result_digest"].startswith("sha256:")
    kb_lines = [r["kb"] for r in records
                if r["record_type"] == "kb_retrieval"]
    assert [k["step"] for k in kb_lines] == \
        ["card_search", "targeted_open", "cite"]
    assert kb_lines[-1]["cards_cited"] == ["kb_hyper0001"]


def test_scripted_transcripts_deterministic(tmp_path):
    """P14 row: scripted transcripts are deterministic — two fresh
    sessions over the same script produce byte-identical transcripts
    (frames carry ordinals, never timestamps)."""
    transcripts = []
    for name in ("a", "b"):
        ws = tmp_path / name
        ws.mkdir()
        store = build_store(ws)
        session = _mint(ws, store)
        _turn(session, three_step_script, store, ws)
        transcripts.append(session.transcript_path.read_bytes())
    assert transcripts[0] == transcripts[1]


def test_loop_exhaustion_is_a_typed_refusal(workspace, store):
    from engine.assistant.loop import MAX_TOOL_ACTIONS, AssistantLoopExhausted

    def always_tool(prompt):
        return json.dumps({"action": "tool", "tool": "chunk_stats",
                           "args": {}})

    session = _mint(workspace, store)
    with pytest.raises(AssistantLoopExhausted):
        _turn(session, always_tool, store, workspace)
    records = read_run(session.logger.path)
    assert records[-1]["error"]["code"] == "assistant_loop_exhausted"
    tool_lines = [r for r in records if r["record_type"] == "tool_call"]
    assert len(tool_lines) == MAX_TOOL_ACTIONS


def test_malformed_wire_logged_then_raised(workspace, store):
    session = _mint(workspace, store)
    with pytest.raises(AssistantWireError):
        _turn(session, lambda prompt: "sure, happy to help!", store,
              workspace)
    records = read_run(session.logger.path)
    assert records[-1]["error"]["code"] == "assistant_wire"
    # spend was already traced before the wire was judged
    assert any(r["record_type"] == "agent_call" for r in records)


def test_unearned_citation_is_refused(workspace, store):
    """The citation gate: citing a doc the session never retrieved gets
    a correction frame, and a model that persists is refused."""
    def stubborn(prompt):
        return json.dumps({"action": "answer", "text": "trust me",
                           "citations": ["steward-runbook.md"]})

    session = _mint(workspace, store)
    with pytest.raises(AssistantWireError, match="never retrieved"):
        _turn(session, stubborn, store, workspace)
    records = read_run(session.logger.path)
    assert records[-1]["error"]["code"] == "assistant_citation_refused"


def test_tool_refusal_relays_and_loop_continues(workspace, store):
    """A refused tool call is a [TOOL_ERROR] frame the model can read —
    the turn still ends in an honest answer."""
    def script(prompt):
        if "[TOOL_RESULT" in prompt:
            return json.dumps({"action": "answer",
                               "text": "The restricted card refused; "
                                       "hypercare is documented.",
                               "citations": ["kb_hyper0001"]})
        if "[TOOL_ERROR" in prompt:
            return json.dumps({"action": "tool", "tool": "open_card",
                               "args": {"kb_id": "kb_hyper0001"}})
        return json.dumps({"action": "tool", "tool": "open_card",
                           "args": {"kb_id": "kb_restr0001"}})

    session = _mint(workspace, store)
    result = _turn(session, script, store, workspace)
    assert result.reply["action"] == "answer"
    assert [t["status"] for t in result.tool_trail] == ["refused", "ok"]
    refused_line = [r for r in read_run(session.logger.path)
                    if r["record_type"] == "tool_call"][0]
    assert "refused" in refused_line["notes"]
    assert "tool_result_digest" not in refused_line


def test_second_turn_keeps_earned_citations(workspace, store):
    """The earned vocabulary is per SESSION: a doc read in turn one may
    ground an answer in turn two without re-reading."""
    session = _mint(workspace, store)
    _turn(session, three_step_script, store, workspace)

    def answer_only(prompt):
        return json.dumps({"action": "answer",
                           "text": "As established, hypercare is covered.",
                           "citations": ["kb_hyper0001"]})

    result = _turn(session, answer_only, store, workspace,
                   message="Say that again briefly.")
    assert result.reply["action"] == "answer"
    users = [r for r in session.transcript() if r["type"] == "user"]
    assert len(users) == 2
