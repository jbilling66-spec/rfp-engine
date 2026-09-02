"""Org purge (P17/C7): the explicit door that takes tier-3 memory —
the whole org tree including its identity record (org names die with
org.json), every remaining lane swept for the purged okb_ ids, and a
frozen brief citing a purged note SURFACED as a finding, never silently
rewritten. Org memory survives a pursuit purge by construction; only
this door removes it."""

import json

import pytest

from engine.kb import purge_org, purge_pursuit_memory
from engine.workspace import PursuitDir, orgs

from tests.kb.fixtures.corpus import ingest_corpus
from tests.helpers import plant_freeze

AT = "2026-08-29T09:00:00Z"


def _org_with_note(workspace):
    org = orgs.create_org(workspace, "Synthetic County", created_by="Pat",
                          at=AT)
    kb_id = orgs.write_org_note(
        workspace, org["org_id"], operator="Pat", at=AT,
        title="Weighting observation",
        body="They weighted change management heavily.")
    return org["org_id"], kb_id


def test_org_purge_takes_the_whole_tree_and_proves_it(tmp_path):
    firm, _ = ingest_corpus(tmp_path / "kb")
    org_id, kb_id = _org_with_note(tmp_path)
    report = purge_org(tmp_path, org_id, actor="owner", firm_store=firm)
    assert report.purged == [kb_id]
    assert report.swept_clean, report.sweep_findings
    assert not (tmp_path / "orgs" / org_id).exists(), \
        "identity record and aliases die with the org"
    accounting = json.loads(
        open(report.accounting_path, encoding="utf-8").read())
    assert accounting["org_cards"] == [kb_id]
    assert accounting["org_record_removed"] is True
    with pytest.raises(RuntimeError, match="unknown org"):
        purge_org(tmp_path, org_id, actor="owner", firm_store=firm)


def test_org_memory_survives_pursuit_purge_and_brief_cites_surface(
        tmp_path):
    firm, _ = ingest_corpus(tmp_path / "kb")
    org_id, kb_id = _org_with_note(tmp_path)
    pursuit = PursuitDir(tmp_path, "pur_one")
    # A frozen brief citing the org note (an internal_kb research
    # finding's source) — immutable record, surfaced not rewritten.
    plant_freeze(pursuit, "bid_brief", {
        "buyer": {"name": "Synthetic County", "org_id": org_id,
                  "research_findings": [
                      {"claim": "they weight change management",
                       "topic": "evaluation", "source_kind": "internal_kb",
                       "source": kb_id}]}})

    # A pursuit purge leaves the org tree standing (siting is the control).
    purge_pursuit_memory(pursuit.root, actor="owner", firm_store=firm)
    assert (tmp_path / "orgs" / org_id / "org.json").exists()
    assert orgs.org_snapshot(tmp_path, org_id) is not None

    # The org purge then FLAGS the frozen brief's citation as a finding.
    report = purge_org(tmp_path, org_id, actor="owner", firm_store=firm)
    assert not report.swept_clean
    assert any(kb_id in f and "brief" in f for f in report.sweep_findings)


def test_lane_purges_answer_to_the_access_gate(tmp_path):
    """An unauthorized actor is refused BEFORE anything mutates — no
    partial purge (the same restricted gate purge_client answers to)."""
    from engine.kb.provenance import ProvenanceAccessDenied

    firm, _ = ingest_corpus(tmp_path / "kb")
    org_id, kb_id = _org_with_note(tmp_path)
    with pytest.raises(ProvenanceAccessDenied):
        purge_org(tmp_path, org_id, actor="Intruder", firm_store=firm)
    assert (tmp_path / "orgs" / org_id / "org.json").exists()
    assert orgs.org_snapshot(tmp_path, org_id) is not None, \
        "the note survives the refused attempt intact"
