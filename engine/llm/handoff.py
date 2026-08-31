"""The handoff caller (P20/B81): the third CallerFor. The exchange is a
pair of files on disk — the engine writes `call-NNNN.request.json` into a
pending-calls directory and blocks, bounded, until the matching
`call-NNNN.response.json` appears; the operator's Claude Code session is
the answerer. The pair is never deleted or moved: an answered exchange on
disk IS the audit record, and an unanswered request left by a timeout is
the honest record of the timeout (B81 D3).

Spends nothing — a handoff call consumes an operator's seat, not an API
key, so there is no RFP_LIVE-style gate (B81 D6): the opt-in is the
explicit per-surface flag plus the no-default pending_dir. Results carry
`handoff/<declared model>` so the transport is unmistakable in every
trace and cost_usd prices the call at its true marginal dollar: zero
(B81 D4).

The bounded wait deliberately inverts the engine's stop-and-return law
for human latency — at the caller only, for judgment steps, because the
crawl-phase transport must stay synchronous from the engine's side
(B79's sketch; B81 D7). The monotonic deadline is the same category of
clock exception the live path's staleness guard is, and argued the same
way: sleep and clock are injectable, so the suite never waits on a wall
clock.
"""

import json
import os
import re
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from engine.llm.caller import CallResult

PROTOCOL = "handoff/v1"

_SEQ_RX = re.compile(r"^call-(\d{4})\.(?:request|response)\.json$")


class HandoffError(RuntimeError):
    pass


class HandoffTimeout(HandoffError):
    pass


def _atomic_write_json(path: Path, obj: dict) -> None:
    # Twin of engine/workspace/pursuit.py's _atomic_write_json, copied
    # rather than imported: an llm -> workspace edge would close an
    # llm -> workspace -> kb -> llm cycle and move the graph's foundation
    # fan-in table for a ten-line function (B81 D2).
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=2, sort_keys=True)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


@dataclass
class HandoffCaller:
    """A CallerFor whose transport is the operator. `pending_dir` has no
    default on purpose — the caller is never constructable by accident;
    each surface that offers it names the directory explicitly."""

    pending_dir: Path
    timeout: float = 900.0
    poll: float = 0.5
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic

    def __post_init__(self) -> None:
        self.pending_dir = Path(self.pending_dir)
        self.pending_dir.mkdir(parents=True, exist_ok=True)
        highest = 0
        for path in self.pending_dir.iterdir():
            match = _SEQ_RX.match(path.name)
            if match:
                highest = max(highest, int(match.group(1)))
        # Resume past every existing exchange — a re-advanced walk issues
        # NEW requests and never overwrites an earlier pair.
        self._seq = highest
        self._lock = threading.Lock()

    def bind(self, *, pursuit_id: str, run_id: str) -> "_BoundHandoff":
        """A per-run view stamping pursuit/run ids into each request so
        the operator can tell whose judgment they are supplying; counter,
        directory, and clock stay shared with this instance."""
        return _BoundHandoff(self, pursuit_id, run_id)

    def call_for(self, agent: str, *, tier: str, prompt: str,
                 system: str = "") -> CallResult:
        return self._exchange(agent, tier, prompt, system, "", "")

    # -- the exchange ------------------------------------------------------

    def _next_seq(self) -> int:
        with self._lock:
            self._seq += 1
            return self._seq

    def _exchange(self, agent: str, tier: str, prompt: str, system: str,
                  pursuit_id: str, run_id: str) -> CallResult:
        seq = self._next_seq()
        request_path = self.pending_dir / f"call-{seq:04d}.request.json"
        response_path = self.pending_dir / f"call-{seq:04d}.response.json"
        _atomic_write_json(request_path, {
            "protocol": PROTOCOL,
            "seq": seq,
            "agent": agent,
            "tier": tier,
            "prompt": prompt,
            "system": system,
            "pursuit_id": pursuit_id,
            "run_id": run_id,
        })
        deadline = self.clock() + self.timeout
        while True:
            if response_path.exists():
                try:
                    payload = json.loads(
                        response_path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    payload = None  # mid-write — not ready, keep polling
                if payload is not None:
                    return self._accept(seq, agent, prompt, system,
                                        payload, response_path)
            if self.clock() >= deadline:
                raise HandoffTimeout(
                    f"no response for {request_path.name} (agent {agent!r}) "
                    f"within {self.timeout:.0f}s — the request file remains; "
                    f"answer it and re-advance, or raise the timeout")
            self.sleep(self.poll)

    def _accept(self, seq: int, agent: str, prompt: str, system: str,
                payload, response_path: Path) -> CallResult:
        name = response_path.name
        if not isinstance(payload, dict):
            raise HandoffError(f"{name}: the response must be a JSON object")
        if payload.get("seq") != seq or payload.get("agent") != agent:
            raise HandoffError(
                f"{name}: echo mismatch — expected seq {seq} / agent "
                f"{agent!r}, got seq {payload.get('seq')!r} / agent "
                f"{payload.get('agent')!r}; the answer must name the "
                f"request it answers")
        model = payload.get("model")
        if not isinstance(model, str) or not model:
            raise HandoffError(
                f"{name}: 'model' must be a non-empty string naming what "
                f"actually answered")
        if model.startswith("fake-"):
            raise HandoffError(
                f"{name}: declared model {model!r} — a fake- prefix would "
                f"price the call at the synthetic table and fabricate spend "
                f"(B81 D4); declare the real answering model")
        text = payload.get("text")
        if not isinstance(text, str):
            raise HandoffError(f"{name}: 'text' must be a string")
        input_tokens = payload.get("input_tokens")
        output_tokens = payload.get("output_tokens")
        return CallResult(
            text=text,
            model=f"handoff/{model}",
            input_tokens=(int(input_tokens) if input_tokens is not None
                          else max(1, (len(system) + len(prompt)) // 4)),
            output_tokens=(int(output_tokens) if output_tokens is not None
                           else max(1, len(text) // 4)),
        )


class _BoundHandoff:
    """The view `make_caller` closures hand to TracedCaller — stamps one
    run's identity into every request it issues."""

    def __init__(self, parent: HandoffCaller, pursuit_id: str, run_id: str):
        self._parent = parent
        self.pursuit_id = pursuit_id
        self.run_id = run_id

    def call_for(self, agent: str, *, tier: str, prompt: str,
                 system: str = "") -> CallResult:
        return self._parent._exchange(agent, tier, prompt, system,
                                      self.pursuit_id, self.run_id)
