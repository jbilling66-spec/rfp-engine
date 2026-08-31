"""The assistant lane's own usage report (P14/C11, B64).

The lane writes proper run logs — every model call a traced `agent_call`,
every executed tool a `tool_call`, every screen hit a `validation` line —
but it lives under `<workspace>/support/assistant/`, which the metrics
walker structurally cannot see (`is_pursuit_dir` wants `brief.json` or
`inbox/`). That separation is deliberate: support spend must never pool
into a pursuit cost series (B36(2)/D21). The defect it left behind is
that NOTHING read those records at all — flags and dollars written
honestly and surfaced nowhere.

So the lane reports on itself, on the telemetry rule: **derive, never
store** — computed from the records at request time, so a figure on the
screen cannot disagree with the record it summarises. No registry
metric, no schema change, no `run.mode` value: the 35-pin stands and the
unmixability holds (the SupportTrace precedent, one lane over).

Honesty rule inherited from `SupportTrace.cost()`: **None until first
use, never a fabricated zero.** A lane nobody has used yet has no
numbers, which is different from a lane that cost nothing."""

import json
from pathlib import Path

from engine.assistant.session import SESSION_CEILING_USD
from engine.runlog import read_run


def lane_root(workspace: Path) -> Path:
    return Path(workspace) / "support" / "assistant" / "runs"


def _transcript_declines(run_dir: Path) -> list[str]:
    """Declined topics come from the transcript, not the run log — a
    decline is a conversational outcome, not a traced event. Same signal
    the advisor's gaps() worklist carries: what the docs do not cover."""
    path = run_dir / "transcript.jsonl"
    if not path.exists():
        return []
    topics = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("type") == "decline" and record.get("topic"):
            topics.append(record["topic"])
    return topics


def lane_usage(workspace: Path) -> dict | None:
    """Everything the lane knows about itself. None before first use."""
    root = lane_root(workspace)
    if not root.is_dir():
        return None
    run_dirs = sorted(d for d in root.iterdir()
                      if (d / "run.jsonl").exists())
    if not run_dirs:
        return None

    sessions, tools, declines = [], {}, {}
    calls = cost = flags = refusals = turns = 0

    for run_dir in run_dirs:
        records = read_run(run_dir / "run.jsonl")
        s_calls = s_cost = s_flags = 0
        s_tools: dict[str, int] = {}
        for record in records:
            kind = record.get("record_type")
            if kind == "agent_call":
                s_calls += 1
                s_cost += record.get("cost_usd", 0.0)
            elif kind == "tool_call":
                name = record["tool"]
                s_tools[name] = s_tools.get(name, 0) + 1
                tools[name] = tools.get(name, 0) + 1
                if "refused" in record.get("notes", ""):
                    refusals += 1
            elif kind == "validation":
                if record["validation"].get("check") == "injection_screen":
                    s_flags += 1
            elif kind == "kb_retrieval":
                if record["kb"].get("step") == "cite":
                    turns += 1

        for topic in _transcript_declines(run_dir):
            row = declines.setdefault(topic, {"topic": topic, "count": 0})
            row["count"] += 1

        calls += s_calls
        cost += s_cost
        flags += s_flags
        sessions.append({
            "session_id": run_dir.name,
            "calls": s_calls,
            "cost_usd": round(s_cost, 6),
            "tools": s_tools,
            "injection_flags": s_flags,
            # the ceiling is per session, so headroom is a per-session fact
            "ceiling_usd": SESSION_CEILING_USD,
            "over_ceiling": round(s_cost, 6) >= SESSION_CEILING_USD,
        })

    return {
        "sessions": sessions,
        "session_count": len(sessions),
        "calls": calls,
        "cost_usd": round(cost, 6),
        "tools": dict(sorted(tools.items())),
        "tool_refusals": refusals,
        "cited_answers": turns,
        "injection_flags": flags,
        "declines": sorted(declines.values(),
                           key=lambda r: (-r["count"], r["topic"])),
        "ceiling_usd": SESSION_CEILING_USD,
        # never a registered metric, never a pursuit cost (B36(2))
        "cost_source": "assistant_lane",
    }
