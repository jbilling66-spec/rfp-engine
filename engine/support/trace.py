"""The support cost lane (B37/D21, G8): the advisor does NOT touch the
run log. Its spend lives in `<workspace>/support/traces.jsonl` — outside
pursuits/, so the per-pursuit cost glob structurally never sees it:
unmixable by TYPE and DIRECTORY, which is what B36(2)'s "structurally
unmixable" means mechanically. Zero schema change: no run.mode value, no
stage value, no registry metric (the 30-pin stands, D29).

Every call lands a line — ok, declined, or error — BEFORE any exception
propagates: a failed support call still costs money and still counts.
Declines carry `topic:` in the detail; the support-gaps worklist parses
exactly that marker (v1 keeper)."""

import hashlib
import json
import os
from pathlib import Path


class SupportTrace:
    def __init__(self, workspace: Path):
        self.path = Path(workspace) / "support" / "traces.jsonl"

    def record(self, *, at: str, by: str, outcome: str, question: str,
               model: str = "", input_tokens: int = 0,
               output_tokens: int = 0, cost_usd: float = 0.0,
               detail: str = "") -> dict:
        line = {"at": at, "by": by, "outcome": outcome,
                "question_digest": hashlib.sha256(
                    question.encode("utf-8")).hexdigest()[:16],
                "model": model, "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost_usd": round(cost_usd, 6)}
        if detail:
            line["detail"] = detail
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(line, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())
        return line

    def lines(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(l) for l in
                self.path.read_text(encoding="utf-8").splitlines()]

    def cost(self) -> dict | None:
        lines = self.lines()
        if not lines:
            return None  # None until first use — never a fabricated zero
        return {
            "calls": len(lines),
            "answered": sum(1 for l in lines if l["outcome"] == "ok"),
            "declined": sum(1 for l in lines if l["outcome"] == "declined"),
            "errors": sum(1 for l in lines if l["outcome"] == "error"),
            "cost_usd": round(sum(l["cost_usd"] for l in lines), 6),
            "cost_source": "support_lane",  # never a registered metric
        }

    def gaps(self) -> list[dict]:
        """Declined topics -> the docs worklist, sorted by demand."""
        counts: dict[str, dict] = {}
        for line in self.lines():
            if line["outcome"] != "declined":
                continue
            detail = line.get("detail", "")
            topic = detail.split("topic: ", 1)[1] if "topic: " in detail \
                else "(unnamed)"
            row = counts.setdefault(topic, {"topic": topic, "count": 0,
                                            "last_at": ""})
            row["count"] += 1
            row["last_at"] = max(row["last_at"], line["at"])
        return sorted(counts.values(),
                      key=lambda r: (-r["count"], r["topic"]))
