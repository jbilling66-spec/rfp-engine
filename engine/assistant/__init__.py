"""The steward assistant (P14/B63) — an interactive, tool-calling loop
over the engine's READ models plus the proposal door, grounded in the
docs/steward and docs/advisor corpora.

The settled boundary (B62): the production pipeline keeps its
deterministic, code-owned loops; this is the one autonomous-loop home
because it is human-supervised, and it reads and proposes only — a
direct card write is structurally unreachable from here, proven by a
named test.
"""

from engine.assistant.docs import DOC_SOURCES, corpus_toc, read_doc
from engine.assistant.loop import (
    AssistantLoopExhausted,
    TurnResult,
    run_turn,
    system_prompt,
)
from engine.assistant.session import (
    SESSION_CEILING_USD,
    AssistantSession,
    UnknownSession,
)
from engine.assistant.tools import (
    TOOLS,
    ToolContext,
    ToolRefused,
    execute_tool,
    tool_catalog,
)
from engine.assistant.usage import lane_usage
from engine.assistant.wire import AssistantWireError, parse_action

__all__ = [
    "AssistantLoopExhausted",
    "AssistantSession",
    "AssistantWireError",
    "DOC_SOURCES",
    "SESSION_CEILING_USD",
    "TOOLS",
    "ToolContext",
    "ToolRefused",
    "TurnResult",
    "UnknownSession",
    "corpus_toc",
    "execute_tool",
    "lane_usage",
    "parse_action",
    "read_doc",
    "run_turn",
    "system_prompt",
    "tool_catalog",
]
