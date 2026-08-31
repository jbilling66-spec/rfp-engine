"""The assistant turn loop (P14/B63): one synchronous, bounded loop per
operator message on the single-turn CallerFor interface — no SDK, no
transport changes. Every model call rides TracedCaller (no call escapes
the trace), every executed action lands a tool_call line with args and
result digests, and every KB/doc-derived result enters the transcript
in the wrap_retrieved frame after the injection screen has seen it.

Rendering is BYTE-STABLE: frames carry ordinals, never timestamps — the
injection twin test depends on the rendered-prompt diff being exactly
the planted sentence."""

from dataclasses import dataclass, field

from engine.assistant.docs import corpus_toc
from engine.assistant.session import SESSION_CEILING_USD, AssistantSession
from engine.assistant.tools import (
    TOOLS,
    ToolContext,
    ToolRefused,
    execute_tool,
    tool_catalog,
)
from engine.assistant.wire import AssistantWireError, parse_action
from engine.intake.screen import screen_text
from engine.llm.caller import SpendBudget, TracedCaller
from engine.llm.frames import wrap_retrieved
from engine.runlog.writer import digest

_AGENT = "steward_assistant"
_STAGE = "assistant"
_TIER = "mid"
MAX_TOOL_ACTIONS = 8
MAX_CALLS = 12
RESULT_CHAR_CAP = 8000
RENDER_CHAR_CAP = 60000

from pathlib import Path as _Path

_PROMPT = _Path(__file__).resolve().parents[2] / "prompts" / "assistant" / "prompt.md"


class AssistantLoopExhausted(RuntimeError):
    """The loop hit its action budget without an answer — a typed
    refusal, never a truncated reply presented as one."""


@dataclass
class TurnResult:
    reply: dict
    tool_trail: list = field(default_factory=list)
    screen_flags: list = field(default_factory=list)
    spent_usd: float = 0.0


def system_prompt() -> str:
    """Static per session state of the world — the model sees what docs
    EXIST (it must read_doc to cite) and what tools it has. Covered by
    config_digest via prompts/assistant/prompt.md."""
    template = _PROMPT.read_text(encoding="utf-8")
    return template.replace("{toc}", corpus_toc()).replace(
        "{tools}", tool_catalog())


def _clip(text: str) -> str:
    if len(text) <= RESULT_CHAR_CAP:
        return text
    return (text[:RESULT_CHAR_CAP]
            + f"\n[... clipped at {RESULT_CHAR_CAP} chars — the on-disk "
              f"record is complete]")


def _render(records: list[dict]) -> str:
    """Transcript → prompt. Ordinal labels only; oldest frames elide
    first when the render cap is hit (the on-disk transcript is never
    truncated)."""
    frames = []
    for record in records:
        kind = record["type"]
        n = record["n"]
        if kind == "user":
            frames.append(f"[USER {n}] {record['text']}")
        elif kind == "assistant":
            frames.append(f"[ASSISTANT {n}] {record['text']}")
        elif kind == "decline":
            frames.append(f"[ASSISTANT {n}] (declined: {record['topic']})")
        elif kind == "tool_call":
            frames.append(f"[TOOL_CALL {n}.{record['k']}] "
                          f"{record['tool']} {record['args_json']}")
        elif kind == "tool_result":
            frames.append(f"[TOOL_RESULT {n}.{record['k']}]\n"
                          f"{record['text']}")
        elif kind == "tool_error":
            frames.append(f"[TOOL_ERROR {n}.{record['k']}] {record['text']}")
        elif kind == "citation_error":
            frames.append(f"[CITATION_ERROR {n}] {record['text']}")
    rendered, total = [], 0
    for frame in reversed(frames):
        total += len(frame) + 2
        if total > RENDER_CHAR_CAP and rendered:
            rendered.append("[EARLIER FRAMES ELIDED — the on-disk "
                            "transcript is complete]")
            break
        rendered.append(frame)
    return "\n\n".join(reversed(rendered))


def run_turn(session: AssistantSession, base_caller, *, store, workspace,
             records_provider, message: str, who: str, at: str,
             prices: dict | None = None) -> TurnResult:
    """One operator message → one bounded tool loop → one reply.

    Raises AssistantWireError (malformed wire → the route's 502),
    AssistantLoopExhausted (budget spent without an answer → 502), and
    CostCeilingExceeded (→ the route's 402) — each with its line already
    on the log."""
    log = session.logger
    docs_earned, cards_earned, proposals_earned = session.earned()
    ctx = ToolContext(store=store, log=log, workspace=workspace,
                      operator=who, at=at,
                      records_provider=records_provider,
                      read_docs=docs_earned, opened_cards=cards_earned,
                      proposal_ids=proposals_earned)
    traced = TracedCaller(
        base_caller, log, ceiling_usd=SESSION_CEILING_USD,
        spent_usd=session.spent_usd(), prices=prices,
        budget=SpendBudget(total_usd=SESSION_CEILING_USD,
                           max_calls=MAX_CALLS))
    transcript = session.transcript()
    n = 1 + sum(1 for r in transcript if r["type"] == "user")
    pending = [{"type": "user", "n": n, "text": message}]
    system = system_prompt()
    trail, flags = [], []
    tool_actions = 0
    citation_retries = 0

    while True:
        result = traced.call(_AGENT, tier=_TIER,
                             prompt=_render(transcript + pending),
                             system=system, stage=_STAGE)
        try:
            action = parse_action(result.text)
        except AssistantWireError as exc:
            log.emit("error", stage=_STAGE, agent=_AGENT,
                     error={"code": "assistant_wire", "message": str(exc),
                            "action_taken": "surfaced_to_human"})
            raise

        if action["action"] == "tool":
            tool_actions += 1
            if tool_actions > MAX_TOOL_ACTIONS:
                log.emit("error", stage=_STAGE, agent=_AGENT,
                         error={"code": "assistant_loop_exhausted",
                                "message": f"no answer within "
                                           f"{MAX_TOOL_ACTIONS} tool actions",
                                "action_taken": "surfaced_to_human"})
                raise AssistantLoopExhausted(
                    f"no answer within {MAX_TOOL_ACTIONS} tool actions")
            name, args = action["tool"], action["args"]
            args_json = _tool_args_json(args)
            k = tool_actions
            pending.append({"type": "tool_call", "n": n, "k": k,
                            "tool": name, "args_json": args_json})
            try:
                kind, result_text = execute_tool(ctx, name, args)
            except ToolRefused as exc:
                log.emit("tool_call", stage=_STAGE, agent=_AGENT, tool=name,
                         tool_args_digest=digest(args_json),
                         notes=f"refused: {exc}")
                pending.append({"type": "tool_error", "n": n, "k": k,
                                "text": str(exc)})
                trail.append({"tool": name, "status": "refused"})
                continue
            log.emit("tool_call", stage=_STAGE, agent=_AGENT, tool=name,
                     tool_args_digest=digest(args_json),
                     tool_result_digest=digest(result_text))
            trail.append({"tool": name, "status": "ok"})
            if kind == "read":
                source = f"assistant:{name}"
                for flag in screen_text(result_text, source=source):
                    flags.append({"pattern_id": flag.pattern_id,
                                  "source": source,
                                  "excerpt": flag.excerpt})
                    log.emit("validation", stage=_STAGE, agent=_AGENT,
                             validation={"check": "injection_screen",
                                         "result": "flag"},
                             notes=f"assistant screen: {flag.pattern_id} "
                                   f"in {source}")
                framed = wrap_retrieved(source, _clip(result_text))
            else:
                framed = _clip(result_text)
            pending.append({"type": "tool_result", "n": n, "k": k,
                            "text": framed})
            continue

        if action["action"] == "answer":
            earned = ctx.read_docs | ctx.opened_cards | ctx.proposal_ids
            bogus = [c for c in action["citations"] if c not in earned]
            if bogus:
                citation_retries += 1
                tool_actions += 1  # counts against the same budget
                if tool_actions > MAX_TOOL_ACTIONS or citation_retries > 2:
                    log.emit("error", stage=_STAGE, agent=_AGENT,
                             error={"code": "assistant_citation_refused",
                                    "message": f"cited without retrieving: "
                                               f"{', '.join(bogus)}",
                                    "action_taken": "surfaced_to_human"})
                    raise AssistantWireError(
                        f"citations never retrieved this session: "
                        f"{', '.join(bogus)}")
                pending.append({
                    "type": "citation_error", "n": n,
                    "text": f"you cited {', '.join(bogus)} without "
                            f"retrieving it — read_doc/open_card first, "
                            f"or drop the citation"})
                continue
            cited_cards = sorted(set(action["citations"]) & ctx.opened_cards)
            if cited_cards:
                from engine.kb.retrieve import emit_kb_retrieval
                emit_kb_retrieval(
                    log, stage=_STAGE, agent=_AGENT,
                    query=f"assistant_cite:turn_{n}", step="cite",
                    cards_returned=cited_cards, cards_opened=cited_cards,
                    cards_cited=cited_cards)
            pending.append({"type": "assistant", "n": n,
                            "text": action["text"],
                            "citations": action["citations"],
                            "earned_docs": sorted(ctx.read_docs),
                            "earned_cards": sorted(ctx.opened_cards),
                            "earned_proposals": sorted(ctx.proposal_ids)})
            for record in pending:
                session.append(record)
            return TurnResult(reply=action, tool_trail=trail,
                              screen_flags=flags,
                              spent_usd=session.spent_usd())

        # decline
        pending.append({"type": "decline", "n": n, "topic": action["topic"],
                        "earned_docs": sorted(ctx.read_docs),
                        "earned_cards": sorted(ctx.opened_cards),
                        "earned_proposals": sorted(ctx.proposal_ids)})
        for record in pending:
            session.append(record)
        return TurnResult(reply=action, tool_trail=trail,
                          screen_flags=flags, spent_usd=session.spent_usd())


def _tool_args_json(args: dict) -> str:
    import json
    return json.dumps(args, sort_keys=True, separators=(",", ":"))
