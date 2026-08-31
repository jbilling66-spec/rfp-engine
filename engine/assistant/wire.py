"""The assistant's action wire — a whitelist-gated discriminated union
(the advisor parse_reply pattern). Three arms, one per reply:

  {"action": "tool", "tool": "<name>", "args": {...}}
  {"action": "answer", "text": "...", "citations": ["<earned name>", ...]}
  {"action": "decline", "topic": "..."}

Proposals are registry TOOLS, not a wire arm — one execution path, one
tool_call logging path, one refusal path (B63). An unknown tool on a
well-formed wire is the EXECUTOR's refusal (the model may self-correct
inside its loop budget); a malformed wire is this module's, and the
route turns it into the advisor's typed 502."""

import json


class AssistantWireError(ValueError):
    pass


def parse_action(text: str) -> dict:
    try:
        start, end = text.index("{"), text.rindex("}") + 1
        obj = json.loads(text[start:end])
    except (ValueError, TypeError):
        raise AssistantWireError("assistant wire is not a JSON object")
    if not isinstance(obj, dict):
        raise AssistantWireError("assistant wire is a scalar, not an object")
    action = obj.get("action")
    if action == "tool":
        tool = obj.get("tool")
        args = obj.get("args") or {}
        if not isinstance(tool, str) or not tool.strip():
            raise AssistantWireError("a tool action names its tool")
        if not isinstance(args, dict):
            raise AssistantWireError("tool args must be an object")
        return {"action": "tool", "tool": tool.strip(), "args": args}
    if action == "answer":
        answer = obj.get("text")
        citations = [c for c in (obj.get("citations") or [])
                     if isinstance(c, str) and c.strip()]
        if not isinstance(answer, str) or not answer.strip():
            raise AssistantWireError("an answer needs text")
        if not citations:
            raise AssistantWireError(
                "an answer must cite at least one retrieved source")
        deduped = list(dict.fromkeys(c.strip() for c in citations))
        return {"action": "answer", "text": answer, "citations": deduped}
    if action == "decline":
        topic = obj.get("topic")
        if not isinstance(topic, str) or not topic.strip():
            raise AssistantWireError("a decline names its topic")
        return {"action": "decline", "topic": topic.strip()}
    raise AssistantWireError(
        f"assistant wire action must be tool|answer|decline, got {action!r}")
