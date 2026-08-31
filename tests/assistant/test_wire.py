"""The action wire's whitelist gates (P14/B63)."""

import pytest

from engine.assistant.wire import AssistantWireError, parse_action


def test_tool_arm_parses_with_default_args():
    action = parse_action('{"action": "tool", "tool": "card_search"}')
    assert action == {"action": "tool", "tool": "card_search", "args": {}}


def test_tool_arm_carries_args():
    action = parse_action(
        'noise {"action": "tool", "tool": "open_card", '
        '"args": {"kb_id": "kb_alpha0001"}} trailing')
    assert action["args"] == {"kb_id": "kb_alpha0001"}


def test_answer_arm_requires_text_and_citations():
    with pytest.raises(AssistantWireError):
        parse_action('{"action": "answer", "text": "", '
                     '"citations": ["steward-runbook.md"]}')
    with pytest.raises(AssistantWireError):
        parse_action('{"action": "answer", "text": "hello", "citations": []}')


def test_answer_citations_dedupe_preserving_order():
    action = parse_action(
        '{"action": "answer", "text": "t", '
        '"citations": ["b.md", "a.md", "b.md"]}')
    assert action["citations"] == ["b.md", "a.md"]


def test_decline_names_its_topic():
    action = parse_action('{"action": "decline", "topic": "pricing"}')
    assert action == {"action": "decline", "topic": "pricing"}
    with pytest.raises(AssistantWireError):
        parse_action('{"action": "decline", "topic": "  "}')


def test_malformed_wires_refused():
    for bad in ("not json at all", "[1, 2]", '"scalar"',
                '{"action": "write_card"}', '{"no": "action"}',
                '{"action": "tool", "tool": ""}',
                '{"action": "tool", "tool": "x", "args": [1]}'):
        with pytest.raises(AssistantWireError):
            parse_action(bad)
