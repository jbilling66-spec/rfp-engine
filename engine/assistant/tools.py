"""The assistant's tool registry — READ models plus the proposal door,
nothing else (B62). Every entry names a function that either reads or
opens a proposal; the KBStore writers (write_card, update_card_front,
rewrite_card, delete_card) appear nowhere here, and the named refusal
test proves an attempt to reach them is refused with the store
untouched.

Results are JSON-rendered with sorted keys so scripted transcripts are
byte-deterministic. Body-bearing results (kind="read") enter the
transcript in the wrap_retrieved frame and pass the injection screen;
the loop owns both steps — this module only executes."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from engine.kb.retrieve import (
    UseRestrictedCard,
    card_search,
    descend,
    targeted_open,
)

_AGENT = "steward_assistant"
_STAGE = "assistant"


class ToolRefused(ValueError):
    """A tool call the registry or governance refuses. Relayed to the
    model as a [TOOL_ERROR] frame — the refusal is the system working."""


@dataclass
class ToolContext:
    store: object
    log: object
    workspace: Path
    operator: str
    at: str
    # Records provider for citation-aware guards (card_detail's cited_in,
    # propose_deprecation's still-cited refusal) — the web layer passes
    # its _workspace_records gatherer so the assistant's guards see the
    # same evidence the curation screen's do.
    records_provider: Callable[[], list] = lambda: []
    # The session's earned citation vocabulary — only what was actually
    # retrieved may be cited (the KB cited ⊆ opened law, one level up).
    read_docs: set = field(default_factory=set)
    opened_cards: set = field(default_factory=set)
    proposal_ids: set = field(default_factory=set)


def _render(payload) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ": "),
                      indent=None, ensure_ascii=False)


def _require(args: dict, spec: dict) -> dict:
    unknown = sorted(set(args) - set(spec))
    if unknown:
        raise ToolRefused(f"unknown argument(s): {', '.join(unknown)}")
    out = {}
    for name, (kind, required) in spec.items():
        if name not in args:
            if required:
                raise ToolRefused(f"missing required argument {name!r}")
            continue
        value = args[name]
        if not isinstance(value, kind):
            raise ToolRefused(
                f"argument {name!r} must be {kind.__name__}")
        out[name] = value
    return out


# -- read tools ------------------------------------------------------------

def _t_read_doc(ctx, args):
    from engine.assistant.docs import read_doc
    a = _require(args, {"name": (str, True)})
    try:
        body = read_doc(a["name"])
    except ValueError as exc:
        raise ToolRefused(str(exc))
    ctx.read_docs.add(a["name"])
    return body


def _t_card_search(ctx, args):
    a = _require(args, {"query": (str, True), "facets": (dict, False),
                        "k": (int, False)})
    kwargs = {"log": ctx.log, "stage": _STAGE, "agent": _AGENT}
    if "k" in a:
        kwargs["k"] = a["k"]
    if "facets" in a:
        kwargs["facets"] = a["facets"]
    found = card_search(ctx.store, a["query"], **kwargs)
    return _render({
        "results": [{"kb_id": r.kb_id, "score": round(r.score, 4),
                     "title": r.card.get("title", ""),
                     "summary": r.card.get("summary", "")}
                    for r in found.results],
        "excluded": found.excluded,
        "note": "open_card earns the right to cite a kb_id; search alone "
                "does not",
    })


def _t_open_card(ctx, args):
    a = _require(args, {"kb_id": (str, True)})
    try:
        body = targeted_open(ctx.store, a["kb_id"], log=ctx.log,
                             stage=_STAGE, agent=_AGENT,
                             query=f"assistant_open:{a['kb_id']}")
    except FileNotFoundError:
        raise ToolRefused(f"no card {a['kb_id']!r}")
    except UseRestrictedCard as exc:
        raise ToolRefused(str(exc))
    ctx.opened_cards.add(a["kb_id"])
    card, _ = ctx.store.read_card(a["kb_id"])
    return _render({"kb_id": a["kb_id"], "title": card.get("title", ""),
                    "layer": card.get("layer"), "body": body})


def _t_descend(ctx, args):
    a = _require(args, {"kb_id": (str, True), "relation": (str, True)})
    if a["relation"] not in ("parent", "siblings", "children"):
        raise ToolRefused("relation must be parent|siblings|children")
    try:
        found = descend(ctx.store, a["kb_id"], a["relation"], log=ctx.log,
                        stage=_STAGE, agent=_AGENT)
    except FileNotFoundError:
        raise ToolRefused(f"no card {a['kb_id']!r}")
    return _render({
        "results": [{"kb_id": r.kb_id, "title": r.card.get("title", "")}
                    for r in found.results],
        "excluded": found.excluded,
    })


def _t_cards_view(ctx, args):
    from engine.kb.curation import cards_view
    a = _require(args, {"q": (str, False), "layer": (str, False),
                        "staleness": (str, False)})
    rows = cards_view(ctx.store, q=a.get("q", ""), layer=a.get("layer", ""),
                      staleness_filter=a.get("staleness", ""), at=ctx.at)
    return _render({"count": len(rows), "cards": rows[:50],
                    "truncated": len(rows) > 50})


def _t_card_detail(ctx, args):
    from engine.kb.curation import card_detail
    a = _require(args, {"kb_id": (str, True)})
    try:
        detail = card_detail(ctx.store, a["kb_id"],
                             records=ctx.records_provider(), at=ctx.at)
    except FileNotFoundError:
        raise ToolRefused(f"no card {a['kb_id']!r}")
    ctx.opened_cards.add(a["kb_id"])
    return _render(detail)


def _t_orphans(ctx, args):
    from engine.kb.curation import orphans_view
    _require(args, {})
    return _render({"orphans": orphans_view(ctx.store)})


def _t_chunk_stats(ctx, args):
    from engine.kb.curation import chunk_size_distribution
    _require(args, {})
    return _render(chunk_size_distribution(ctx.store))


def _t_proposals_queue(ctx, args):
    from engine.contracts import ContractError
    from engine.flywheel.proposals import ProposalStore
    _require(args, {})
    try:
        proposed = ProposalStore(ctx.store.root).list(status="proposed")
    except ContractError as exc:  # M-30: named, not a crash
        raise ToolRefused(str(exc))
    rows = [{"proposal_id": p["proposal_id"], "kind": p["kind"],
             "kb_id": p.get("kb_id"), "door": p["source"].get("door"),
             "created": p["created"], "note": p.get("note", "")}
            for p in proposed]
    return _render({"proposed": rows})


def _t_reconciliation_report(ctx, args):
    a = _require(args, {"doc_id": (str, False)})
    recon = ctx.store.root / "reconciliation"
    reports = []
    if recon.is_dir():
        for path in sorted(recon.glob("*.json")):
            report = json.loads(path.read_text(encoding="utf-8"))
            if "doc_id" in a and report.get("doc_id") != a["doc_id"]:
                continue
            reports.append(report)
    return _render({"reports": reports})


def _t_pursuit_status(ctx, args):
    from engine.support.advisor import pursuit_digest
    a = _require(args, {"pursuit_id": (str, True)})
    try:
        digest = pursuit_digest(ctx.workspace, a["pursuit_id"])
    except FileNotFoundError:
        raise ToolRefused(f"no pursuit {a['pursuit_id']!r}")
    cost = 0.0
    runs = Path(ctx.workspace) / a["pursuit_id"] / "runs"
    if runs.is_dir():
        for run_file in sorted(runs.glob("*/run.jsonl")):
            for line in run_file.read_text(encoding="utf-8").splitlines():
                record = json.loads(line)
                if record.get("record_type") == "agent_call":
                    cost += record.get("cost_usd", 0.0)
    return _render({"digest": digest, "cost_to_date_usd": round(cost, 4)})


def _t_plan_import(ctx, args):
    from engine.kb.xlsx import WorkbookError, plan_import
    a = _require(args, {"path": (str, True)})
    path = (Path(ctx.workspace) / a["path"]).resolve()
    if not str(path).startswith(str(Path(ctx.workspace).resolve()) + "/"):
        raise ToolRefused("path must stay inside the workspace")
    if path.suffix != ".xlsx" or not path.is_file():
        raise ToolRefused(f"{a['path']!r} is not an existing .xlsx "
                          f"under the workspace")
    try:
        return _render(plan_import(ctx.store, path))
    except WorkbookError as exc:
        raise ToolRefused(str(exc))


# -- proposal-door tools ---------------------------------------------------

def _t_propose_edit(ctx, args):
    from engine.kb.curation import CurationRefused, propose_edit
    a = _require(args, {"kb_id": (str, True), "changes": (dict, True),
                        "note": (str, False)})
    try:
        proposal = propose_edit(
            ctx.store, a["kb_id"], a["changes"], operator=ctx.operator,
            at=ctx.at, door="assistant",
            note=a.get("note") or
            f"Drafted by the steward assistant for {ctx.operator}.")
    except FileNotFoundError:
        raise ToolRefused(f"no card {a['kb_id']!r}")
    except CurationRefused as exc:
        raise ToolRefused(str(exc))
    ctx.proposal_ids.add(proposal["proposal_id"])
    return _render({"proposal_id": proposal["proposal_id"],
                    "status": proposal["status"],
                    "note": "awaiting steward review in the KB inbox"})


def _t_propose_deprecation(ctx, args):
    from engine.kb.curation import CurationRefused, propose_deprecation
    a = _require(args, {"kb_id": (str, True), "note": (str, False)})
    try:
        proposal = propose_deprecation(
            ctx.store, a["kb_id"], operator=ctx.operator, at=ctx.at,
            records=ctx.records_provider(), door="assistant",
            note=a.get("note") or
            f"Deprecation drafted by the steward assistant for "
            f"{ctx.operator}.")
    except FileNotFoundError:
        raise ToolRefused(f"no card {a['kb_id']!r}")
    except CurationRefused as exc:
        raise ToolRefused(str(exc))
    ctx.proposal_ids.add(proposal["proposal_id"])
    return _render({"proposal_id": proposal["proposal_id"],
                    "status": proposal["status"],
                    "note": "awaiting steward review in the KB inbox"})


@dataclass(frozen=True)
class ToolSpec:
    fn: Callable
    kind: str  # "read" | "propose"
    summary: str


TOOLS: dict[str, ToolSpec] = {
    "read_doc": ToolSpec(_t_read_doc, "read",
                         "read one grounding document by name"),
    "card_search": ToolSpec(_t_card_search, "read",
                            "rank KB cards for a query (optional facets, k)"),
    "open_card": ToolSpec(_t_open_card, "read",
                          "open one card's full body by kb_id"),
    "descend": ToolSpec(_t_descend, "read",
                        "a card's parent|siblings|children in its document"),
    "cards_view": ToolSpec(_t_cards_view, "read",
                           "browse/filter the card catalog (q, layer, "
                           "staleness)"),
    "card_detail": ToolSpec(_t_card_detail, "read",
                            "one card with citations, staleness, notes"),
    "orphans": ToolSpec(_t_orphans, "read",
                        "the orphaned-card review queue"),
    "chunk_stats": ToolSpec(_t_chunk_stats, "read",
                            "chunk-size distribution (recorded, never "
                            "enforced)"),
    "proposals_queue": ToolSpec(_t_proposals_queue, "read",
                                "open proposals awaiting steward review"),
    "reconciliation_report": ToolSpec(_t_reconciliation_report, "read",
                                      "re-ingest reconciliation reports "
                                      "(optional doc_id)"),
    "pursuit_status": ToolSpec(_t_pursuit_status, "read",
                               "facts-only pursuit digest + cost to date"),
    "plan_import": ToolSpec(_t_plan_import, "read",
                            "dry-run a KB workbook import (writes nothing)"),
    "propose_edit": ToolSpec(_t_propose_edit, "propose",
                             "open an update_card proposal (kb_id, changes)"),
    "propose_deprecation": ToolSpec(_t_propose_deprecation, "propose",
                                    "open a deprecation proposal (kb_id)"),
}


def tool_catalog() -> str:
    """Deterministic rendering for the system prompt."""
    return "\n".join(f"- {name} ({spec.kind}): {spec.summary}"
                     for name, spec in TOOLS.items())


def execute_tool(ctx: ToolContext, name: str, args: dict) -> tuple[str, str]:
    """Run one registry tool. Returns (kind, result_text). ToolRefused
    propagates — the loop relays it as a [TOOL_ERROR] frame."""
    spec = TOOLS.get(name)
    if spec is None:
        raise ToolRefused(
            f"{name!r} is not a tool — the registry is: "
            f"{', '.join(TOOLS)}")
    return spec.kind, spec.fn(ctx, args)
