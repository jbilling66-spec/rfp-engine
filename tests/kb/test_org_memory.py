"""Tier-3 org memory (P17/C6, B69§2): firm-authored observations about
a buyer that persist ACROSS pursuits — human-linked at gate_0 (declared,
never inferred), sited outside every pursuit tree, joining research
retrieval only (B75§1c — never the mapper, never drafting), and
structurally incapable of retaining buyer text (B69§3: the note door is
the only writer and stamps human_authored; the buyer-authored ingest
gate holds for ANY store)."""

import json

import pytest

from engine.contracts import ContractError
from engine.kb import (
    KBStore,
    Lanes,
    SourceDoc,
    card_search,
    ingest_document,
)
from engine.cli.slice import KB_ROOT, _extras
from engine.cli.slice_script import ci_script
from engine.intake.gate import approve_gate0
from engine.llm import FakeCaller, TracedCaller, effective_config
from engine.pipeline.driver import StageRun
from engine.runlog import RunLogger, read_run
from engine.version import engine_version
from engine.workspace import PursuitDir, orgs
from tests.intake.fixtures.packages import run_package

AT = "2026-08-29T09:00:00Z"


def test_org_note_persists_across_pursuits_and_joins_research_only(tmp_path):
    org = orgs.create_org(tmp_path, "Synthetic County", created_by="Pat",
                          at=AT)
    okb = orgs.write_org_note(
        tmp_path, org["org_id"], operator="Pat", at=AT,
        title="Evaluation weighting observation",
        body="This organization weighted change management heavily in "
             "prior evaluations.")
    assert okb.startswith("okb_")

    def make_caller(log):
        return TracedCaller(FakeCaller(ci_script()), log)

    for pid in ("pur_one", "pur_two"):
        pursuit = PursuitDir(tmp_path, pid)
        pursuit.write_json("brief.json",
                           {"buyer": {"name": "Synthetic County",
                                      "org_id": org["org_id"]}})
        research = StageRun(pursuit, make_caller, "dry_run", "research",
                            kb_root=KB_ROOT, extras=_extras)
        assert isinstance(research.lanes, Lanes)
        assert research.lanes.org is not None
        assert research.lanes.org_id == org["org_id"]
        header = [r for r in read_run(pursuit.root / "runs" /
                                      research.log.run_id / "run.jsonl")
                  if r["record_type"] == "run_start"][-1]
        assert header["run"]["org_kb_snapshot"] == \
            orgs.org_snapshot(tmp_path, org["org_id"])
        result = card_search(
            research.lanes, "how does this buyer weight change management",
            log=research.log, stage="research_internal",
            agent="internal_researcher")
        assert okb in [r.kb_id for r in result.results]

        # B75§1c: the mapper's stage never joins the org lane.
        planning = StageRun(pursuit, make_caller, "dry_run", "planning",
                            kb_root=KB_ROOT, extras=_extras)
        assert isinstance(planning.lanes, KBStore)
        header = [r for r in read_run(pursuit.root / "runs" /
                                      planning.log.run_id / "run.jsonl")
                  if r["record_type"] == "run_start"][-1]
        assert "org_kb_snapshot" not in header["run"]


def test_gate0_human_link_step_stamps_the_brief(tmp_path):
    pursuit, _report = run_package(tmp_path / "p", "pdf")
    log = RunLogger(pursuit.root, pursuit.new_run_id(),
                    pursuit.pursuit_id)
    log.run_start(mode="dry_run", engine_version=engine_version(),
                  config=effective_config(), kb_snapshot="kb@empty")
    result = approve_gate0(
        pursuit, log, decision="approved", actor="Pat Lead", at=AT,
        org={"create": {"name": "Synthetic County"}})
    log.run_end(status="completed")
    assert result.decision == "approved"
    brief = pursuit.read_artifact("brief.json")
    org_id = brief["buyer"]["org_id"]
    assert org_id == "org_0001"
    workspace = pursuit.root.parent
    record = orgs.read_org(workspace, org_id)
    assert "Synthetic County" in record["known_as"]
    buyer_name = brief["buyer"].get("name", "")
    if buyer_name:
        assert buyer_name in record["known_as"]
    gate_line = [r for r in read_run(pursuit.root / "runs" /
                                     log.run_id / "run.jsonl")
                 if r["record_type"] == "gate"][-1]
    assert f"org:{org_id}" in gate_line["gate"]["edits_summary"]


def test_org_link_shape_is_exactly_one_of_link_or_create(tmp_path):
    pursuit, _ = run_package(tmp_path / "p", "pdf")
    log = RunLogger(pursuit.root, pursuit.new_run_id(),
                    pursuit.pursuit_id)
    log.run_start(mode="dry_run", engine_version=engine_version(),
                  config=effective_config(), kb_snapshot="kb@empty")
    with pytest.raises(ContractError, match="exactly one"):
        approve_gate0(pursuit, log, decision="approved", actor="Pat",
                      at=AT, org={})
    with pytest.raises(ContractError, match="unknown org"):
        approve_gate0(pursuit, log, decision="approved", actor="Pat",
                      at=AT, org={"org_id": "org_9999"})


def test_org_store_never_retains_buyer_text(tmp_path):
    """B69§3 structurally: the note door stamps human_authored/firm and
    refuses empty input; the buyer-authored ingest refusal holds for ANY
    KBStore — an org root included — so buyer prose has no path in."""
    org = orgs.create_org(tmp_path, "Synthetic County", created_by="Pat",
                          at=AT)
    kb_id = orgs.write_org_note(
        tmp_path, org["org_id"], operator="Pat", at=AT,
        title="Phasing preference",
        body="They responded well to the phased-award framing.")
    store = orgs.org_store(tmp_path, org["org_id"])
    card, _body = store.read_card(kb_id)
    assert card["content_origin"] == "human_authored"
    with pytest.raises(ContractError):
        orgs.write_org_note(tmp_path, org["org_id"], operator="Pat",
                            at=AT, title="", body="pasted buyer prose")

    log = RunLogger(store.root, "run_0001", "kb")
    caller = TracedCaller(FakeCaller({}), log)
    doc = SourceDoc(doc_id="buyer_rfp", text="The County requires…",
                    source_client="Synthetic County",
                    source_pursuit="pur_one", outcome="open",
                    date="2026-08-29", authored_by="buyer")
    report = ingest_document(store, caller, log, doc)
    assert report.status == "refused"
    assert json.loads(
        (store.root / "runs" / "run_0001" / "run.jsonl")
        .read_text().splitlines()[-1])["error"]["code"] \
        == "buyer_authored_source"
