"""The gate-decision request digest (P25 item 1; register P0-5, P2-13).

A gate decision converges on WHAT was decided, never on WHEN: the key is
(decision, actor, request_sha256), where the digest covers the semantic
request — decision, notes, edits/answers/corrections/skips, org, the
collapse flag — and never the clock, the wait, or per-submission
transport (effort, actor_role). A crash between the stamp and the
checkpoint recovers through a same-request resubmit from the browser,
whose clock is necessarily different; a DIFFERENT request in that window
refuses instead of converging silently onto the first attempt's edits —
the silent-loss class the session-34 sweep named (B95 §3).

Records written before P25 carry no digest; they converge on
(decision, actor) alone — the acceptance's literal rule (B97 §2).
"""

import hashlib
import json

SEMANTIC_FIELDS = ("decision", "notes", "edits", "corrections", "answers",
                   "skips", "org", "gates_collapsed")
_EMPTY = (None, {}, [], "")


def _prune(value):
    """Canonical form: None and empty containers/strings drop out at
    every level, so `edits=None` and `edits={"dispose": []}` are the same
    request (tests/planning/test_gate2.py replays exactly that)."""
    if isinstance(value, dict):
        out = {k: _prune(v) for k, v in value.items()}
        return {k: v for k, v in out.items()
                if not (v is False or v in _EMPTY)}
    if isinstance(value, (list, tuple)):
        return [_prune(v) for v in value]
    return value


def request_digest(**fields) -> str:
    """sha256 over the canonical JSON of the semantic fields. A field
    outside SEMANTIC_FIELDS is refused: the clock and transport never
    enter the key by accident."""
    unknown = set(fields) - set(SEMANTIC_FIELDS)
    if unknown:
        raise ValueError(
            f"non-semantic field(s) in the gate key: {sorted(unknown)} — "
            "the clock and per-submission transport never enter the digest")
    canon = {}
    for name in SEMANTIC_FIELDS:
        if name in fields:
            pruned = _prune(fields[name])
            if pruned is False or pruned in _EMPTY:
                continue
            canon[name] = pruned
    payload = json.dumps(canon, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def same_request(record: dict, *, actor: str, digest: str, actor_key: str,
                 decision: str | None = None) -> bool:
    """True when `record` — a gate checkpoint (`actor`, `decision`) or a
    stamp block (`approved_by`) — is the same decision by the same
    actor: the decision when the record carries one, the actor, and the
    digest when the record carries one (pre-P25 records carry none)."""
    if decision is not None and record.get("decision") != decision:
        return False
    if record.get(actor_key) != actor:
        return False
    recorded = record.get("request_sha256")
    return recorded is None or recorded == digest
