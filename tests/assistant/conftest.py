"""Fixtures for the steward-assistant suite (P14).

House discipline: state is built directly through the store (the
test_curation pattern), the log is a real RunLogger over tmp, and
nothing here touches the committed KB."""

import json

import pytest

from engine.assistant.tools import ToolContext
from engine.kb.store import KBStore
from engine.runlog.writer import RunLogger

FIXED_AT = "2026-08-24T09:00:00"

PROV = {"source_pursuit": "pur_x", "source_client": "Fixture County",
        "date": "2026-01-01", "ingested_by": "ingestion_agent"}


def build_store(root) -> KBStore:
    store = KBStore(root / "kb")
    store.write_card(
        {"kb_id": "kb_alpha0001", "layer": "corpus",
         "doc_kind": "section_exemplar", "title": "Data Migration Approach",
         "summary": "Seven mock conversions across two ledgers.",
         "owner": "Delivery Lead"},
        "We rehearse the conversion seven times against mock ledgers.",
        PROV, {})
    store.write_card(
        {"kb_id": "kb_hyper0001", "layer": "corpus", "doc_kind": "past_response",
         "title": "Hypercare Support Window",
         "summary": "Hypercare staffing for the stabilization window.",
         "owner": "Delivery Lead"},
        "Hypercare runs two weeks with named escalation contacts.",
        PROV, {})
    store.write_card(
        {"kb_id": "kb_restr0001", "layer": "corpus", "doc_kind": "past_response",
         "title": "Escalation runbook", "summary": "Named engagement detail.",
         "owner": "Delivery Lead", "use_restriction": True,
         "sensitivity": "restricted"},
        "Restricted body.", PROV, {})
    store.write_card(
        {"kb_id": "kb_fact00001", "layer": "fact_sheet", "doc_kind": "fact",
         "title": "Certified staff count", "summary": "Verified headcount.",
         "owner": "Compliance Lead", "verified_date": "2026-01-01"},
        "Forty certified consultants.", PROV, {})
    return store


@pytest.fixture
def workspace(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    return ws


@pytest.fixture
def store(workspace):
    return build_store(workspace)


@pytest.fixture
def log(workspace):
    return RunLogger(workspace / "support" / "assistant", "sas_test0001",
                     "assistant")


@pytest.fixture
def ctx(store, log, workspace):
    return ToolContext(store=store, log=log, workspace=workspace,
                       operator="Sam Steward", at=FIXED_AT)


def make_pursuit(workspace, pursuit_id: str) -> None:
    root = workspace / pursuit_id
    root.mkdir(parents=True)
    (root / "brief.json").write_text(
        json.dumps({"status": "approved"}), encoding="utf-8")
