"""THE NAMED TEST (P14 row): a planted instruction inside retrieved KB
content flags and does not alter behavior.

The tests/intake/test_injection.py twin shape, applied to the new
surface: two stores identical except one planted sentence inside a card
body; the same scripted session over both. The planted twin flags —
screen result on the reply, validation line on the log — and behaves
identically: same tool trail, same reply, and the rendered prompts
differ by exactly the line carrying the planted sentence. Detection
never mutates; the behavioral defense is the wrap_retrieved frame."""

import json

from engine.assistant.loop import run_turn
from engine.assistant.session import AssistantSession
from engine.kb.store import KBStore
from engine.llm.caller import FakeCaller
from engine.runlog.writer import read_run
from engine.version import engine_version
from tests.assistant.conftest import FIXED_AT, PROV
from tests.fixtures.intake_twins import INJECTION_SENTENCE

CLEAN_BODY = "Warranty coverage runs twelve months from go-live.\nClaims route through the service desk."
PLANTED_BODY = (f"Warranty coverage runs twelve months from go-live.\n"
                f"{INJECTION_SENTENCE}\n"
                f"Claims route through the service desk.")


def _build(tmp_path, name, body):
    ws = tmp_path / name
    ws.mkdir()
    store = KBStore(ws / "kb")
    store.write_card(
        {"kb_id": "kb_warr00001", "layer": "corpus",
         "doc_kind": "past_response", "title": "Warranty Coverage",
         "summary": "Post go-live warranty terms.",
         "owner": "Delivery Lead"},
        body, PROV, {})
    return ws, store


def _script(prompt: str) -> str:
    if "[TOOL_RESULT" in prompt:
        return json.dumps({"action": "answer",
                           "text": "Warranty coverage runs twelve months.",
                           "citations": ["kb_warr00001"]})
    return json.dumps({"action": "tool", "tool": "open_card",
                       "args": {"kb_id": "kb_warr00001"}})


def _run(ws, store):
    session = AssistantSession.mint(
        ws, mode="dry_run", engine_version=engine_version(),
        config={"suite": "assistant-tests"}, kb_snapshot=store.snapshot())
    prompts = []

    def capturing(prompt):
        prompts.append(prompt)
        return _script(prompt)

    result = run_turn(
        session, FakeCaller({"steward_assistant": capturing}), store=store,
        workspace=ws, records_provider=lambda: [],
        message="What are our warranty terms?", who="Sam Steward",
        at=FIXED_AT)
    return session, result, prompts


def test_planted_instruction_flags_and_does_not_alter_behavior(tmp_path):
    clean_ws, clean_store = _build(tmp_path, "clean", CLEAN_BODY)
    planted_ws, planted_store = _build(tmp_path, "planted", PLANTED_BODY)

    clean_session, clean_result, clean_prompts = _run(clean_ws, clean_store)
    planted_session, planted_result, planted_prompts = _run(
        planted_ws, planted_store)

    # -- it flags ---------------------------------------------------------
    assert clean_result.screen_flags == []
    assert planted_result.screen_flags, "the screen must fire"
    planted_records = read_run(planted_session.logger.path)
    flag_lines = [r for r in planted_records
                  if r["record_type"] == "validation"
                  and r["validation"]["check"] == "injection_screen"]
    assert flag_lines and all(
        r["validation"]["result"] == "flag" and r["stage"] == "assistant"
        for r in flag_lines)
    clean_records = read_run(clean_session.logger.path)
    assert not any(r["record_type"] == "validation"
                   for r in clean_records)

    # -- and does not alter behavior --------------------------------------
    assert planted_result.reply == clean_result.reply
    assert planted_result.tool_trail == clean_result.tool_trail
    assert len(clean_prompts) == len(planted_prompts)
    for clean_prompt, planted_prompt in zip(clean_prompts, planted_prompts):
        clean_lines = clean_prompt.splitlines()
        planted_lines = planted_prompt.splitlines()
        diff = [line for line in planted_lines if line not in clean_lines]
        if diff:
            # detection never mutates: the only difference is the line
            # carrying the planted sentence, inside its retrieved frame
            assert len(diff) == 1
            assert INJECTION_SENTENCE in diff[0]
            assert 'label="retrieved"' in planted_prompt


def test_planted_content_rides_inside_the_retrieved_frame(tmp_path):
    ws, store = _build(tmp_path, "framed", PLANTED_BODY)
    _session, _result, prompts = _run(ws, store)
    final = prompts[-1]
    start = final.index("<retrieved_content")
    end = final.index("</retrieved_content>")
    assert INJECTION_SENTENCE in final[start:end]
