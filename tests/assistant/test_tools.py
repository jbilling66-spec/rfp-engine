"""The tool registry: reads plus the proposal door, nothing else — and
the named direct-write refusal the P14 row demands."""

import json

import pytest

from engine.assistant.tools import TOOLS, ToolRefused, execute_tool
from engine.kb.store import snapshot_id
from tests.assistant.conftest import FIXED_AT, make_pursuit


def _read_lines(log):
    return [json.loads(line) for line in
            log.path.read_text(encoding="utf-8").splitlines()]


# ------------------------------------------------------------ the registry

def test_registry_is_reads_and_proposal_door_only():
    """B62's constraint, introspected: every tool is a read or a
    proposal-door open. The propose set is exactly the two doors."""
    kinds = {name: spec.kind for name, spec in TOOLS.items()}
    assert set(kinds.values()) <= {"read", "propose"}
    assert {n for n, k in kinds.items() if k == "propose"} == \
        {"propose_edit", "propose_deprecation"}


def test_direct_write_is_refused_and_store_untouched(ctx):
    """THE NAMED TEST (P14 row): a wire naming any store writer — or any
    name outside the registry — is refused, and the store's content
    snapshot is byte-identical afterward."""
    before = snapshot_id(ctx.store.root)
    for name in ("write_card", "update_card_front", "rewrite_card",
                 "delete_card", "new_card", "merge_batch", "purge_client"):
        with pytest.raises(ToolRefused):
            execute_tool(ctx, name, {"kb_id": "kb_alpha0001"})
    assert snapshot_id(ctx.store.root) == before


def test_unknown_argument_refused(ctx):
    with pytest.raises(ToolRefused):
        execute_tool(ctx, "card_search", {"query": "x", "bogus": 1})
    with pytest.raises(ToolRefused):
        execute_tool(ctx, "open_card", {})


# ------------------------------------------------------------ reads

def test_card_search_returns_results_and_logs_retrieval(ctx):
    kind, result = execute_tool(ctx, "card_search", {"query": "hypercare"})
    assert kind == "read"
    payload = json.loads(result)
    assert payload["results"][0]["kb_id"] == "kb_hyper0001"
    lines = _read_lines(ctx.log)
    assert lines[-1]["record_type"] == "kb_retrieval"
    assert lines[-1]["stage"] == "assistant"
    assert lines[-1]["kb"]["step"] == "card_search"


def test_open_card_earns_citation_right(ctx):
    _, result = execute_tool(ctx, "open_card", {"kb_id": "kb_hyper0001"})
    assert "Hypercare runs two weeks" in result
    assert "kb_hyper0001" in ctx.opened_cards
    assert _read_lines(ctx.log)[-1]["kb"]["step"] == "targeted_open"


def test_use_restricted_card_refused_with_the_refusal_on_the_trace(ctx):
    with pytest.raises(ToolRefused):
        execute_tool(ctx, "open_card", {"kb_id": "kb_restr0001"})
    assert "kb_restr0001" not in ctx.opened_cards
    line = _read_lines(ctx.log)[-1]
    assert line["record_type"] == "kb_retrieval"
    assert line["kb"]["excluded"] == ["kb_restr0001"]


def test_read_doc_earns_citation_right(ctx):
    _, result = execute_tool(ctx, "read_doc",
                             {"name": "steward-runbook.md"})
    assert "steward" in result.lower()
    assert "steward-runbook.md" in ctx.read_docs
    with pytest.raises(ToolRefused):
        execute_tool(ctx, "read_doc", {"name": "nope.md"})


def test_pursuit_status_never_creates_a_pursuit(ctx):
    with pytest.raises(ToolRefused):
        execute_tool(ctx, "pursuit_status", {"pursuit_id": "pur_ghost"})
    assert not (ctx.workspace / "pur_ghost").exists()
    make_pursuit(ctx.workspace, "pur_real")
    _, result = execute_tool(ctx, "pursuit_status",
                             {"pursuit_id": "pur_real"})
    payload = json.loads(result)
    assert "pur_real" in payload["digest"]
    assert payload["cost_to_date_usd"] == 0.0


def test_plan_import_path_guard(ctx):
    with pytest.raises(ToolRefused):
        execute_tool(ctx, "plan_import", {"path": "../outside.xlsx"})
    with pytest.raises(ToolRefused):
        execute_tool(ctx, "plan_import", {"path": "absent.xlsx"})


# ------------------------------------------------------------ the door

def test_propose_edit_opens_assistant_door_proposal(ctx):
    """P14 row: writes land as proposals. The card itself is untouched,
    the proposal carries door=assistant + the human operator."""
    card_before = ctx.store.read_card("kb_alpha0001")
    kind, result = execute_tool(ctx, "propose_edit", {
        "kb_id": "kb_alpha0001",
        "changes": {"summary": "Eight mock conversions across two ledgers."},
    })
    assert kind == "propose"
    payload = json.loads(result)
    pid = payload["proposal_id"]
    assert pid in ctx.proposal_ids
    proposal_path = ctx.store.root / "proposals" / f"{pid}.json"
    proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
    assert proposal["source"]["door"] == "assistant"
    assert proposal["source"]["operator"] == "Sam Steward"
    assert proposal["status"] == "proposed"
    assert ctx.store.read_card("kb_alpha0001") == card_before


def test_propose_edit_governance_field_refused(ctx):
    with pytest.raises(ToolRefused):
        execute_tool(ctx, "propose_edit", {
            "kb_id": "kb_alpha0001",
            "changes": {"edit_survival": 1.0},
        })


def test_propose_deprecation_opens_assistant_door_proposal(ctx):
    _, result = execute_tool(ctx, "propose_deprecation",
                             {"kb_id": "kb_hyper0001"})
    pid = json.loads(result)["proposal_id"]
    proposal = json.loads(
        (ctx.store.root / "proposals" / f"{pid}.json").read_text(
            encoding="utf-8"))
    assert proposal["source"]["door"] == "assistant"
    assert proposal["kind"] == "deprecate_card"
    assert ctx.store.card_exists("kb_hyper0001")  # deprecate ≠ delete
