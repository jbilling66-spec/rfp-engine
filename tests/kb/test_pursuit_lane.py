"""Tier-2 pursuit memory (P17/C4, B69§2): supplemental documents become
retrievable pursuit-scoped cards — beside the firm KB, provenance
distinguishable in the trace (the pkb_ prefix + the line's lanes field),
never entering the firm corpus. The deposit door is deterministic and
zero-spend; unchunkable formats refuse loudly; the StageRun joins the
lane only where it belongs (B75§1c — validation never sees it), and a
fact-shaped memory card can never reach the fact catalog (the Tier-1
firewall, both belts).
"""

import pytest

from engine.contracts import ContractError
from engine.kb import KBStore, Lanes, card_search
from engine.kb.pursuit_memory import (
    deposit_supplemental,
    memory_snapshot,
    memory_store,
)
from engine.cli.slice import KB_ROOT, _extras
from engine.cli.slice_script import ci_script
from engine.llm import FakeCaller, TracedCaller
from engine.pipeline.driver import StageRun
from engine.runlog import RunLogger, read_run
from engine.validation.claims import fact_catalog
from engine.workspace import PursuitDir

from tests.kb.fixtures.corpus import ingest_corpus

SUPPLEMENT = """# Prior proposal — data migration approach
Legacy ledgers converted in four waves with reconciliation checkpoints.

# Interface inventory
Eleven interfaces, two retired at cutover.
"""


def _pursuit(tmp_path, pursuit_id="pur_mem"):
    return PursuitDir(tmp_path, pursuit_id)


def _log(pursuit, run_id="run_0001"):
    return RunLogger(pursuit.root, run_id, pursuit.pursuit_id)


def _lines(pursuit, run_id="run_0001"):
    return read_run(pursuit.root / "runs" / run_id / "run.jsonl")


def test_deposit_chunks_by_heading_and_is_idempotent(tmp_path):
    pursuit = _pursuit(tmp_path)
    (pursuit.root / "inbox" / "prior-proposal.md").write_text(SUPPLEMENT)
    log = _log(pursuit)
    minted = deposit_supplemental(pursuit, "prior-proposal.md",
                                  authored_by="firm", log=log,
                                  stage="intake")
    assert len(minted) == 2
    assert all(kb_id.startswith("pkb_") for kb_id in minted)
    store = memory_store(pursuit.root)
    cards = store.list_cards()
    assert {c["title"] for c in cards} == {
        "Prior proposal — data migration approach", "Interface inventory"}
    assert all(c["layer"] == "corpus" for c in cards), \
        "the door only ever mints corpus — never fact_sheet"
    artifact_lines = [r for r in _lines(pursuit)
                      if r["record_type"] == "artifact"]
    assert artifact_lines[-1]["artifact"]["kind"] == "pursuit_memory"
    assert memory_snapshot(pursuit.root) is not None
    # Content-anchored ids make the deposit idempotent.
    again = deposit_supplemental(pursuit, "prior-proposal.md",
                                 authored_by="firm", log=log,
                                 stage="intake")
    assert again == []


def test_deposit_validates_authorship_and_refuses_unchunkable(tmp_path):
    pursuit = _pursuit(tmp_path)
    (pursuit.root / "inbox" / "notes.md").write_text("just notes\n")
    (pursuit.root / "inbox" / "contract.pdf").write_bytes(b"%PDF-1.4 stub")
    log = _log(pursuit)
    with pytest.raises(ContractError):
        deposit_supplemental(pursuit, "notes.md", authored_by="martian",
                             log=log, stage="intake")
    assert deposit_supplemental(pursuit, "contract.pdf",
                                authored_by="buyer", log=log,
                                stage="intake") == []
    errors = [r for r in _lines(pursuit) if r["record_type"] == "error"]
    assert errors[-1]["error"]["code"] == "memory_deposit_unsupported"
    assert errors[-1]["error"]["action_taken"] == "surfaced_to_human"


def test_deposited_docs_answer_beside_firm_cards_with_lane_provenance(
        tmp_path):
    firm, reports = ingest_corpus(tmp_path / "kb")
    assert all(r.status == "ingested" for r in reports)
    pursuit = _pursuit(tmp_path)
    (pursuit.root / "inbox" / "prior-proposal.md").write_text(SUPPLEMENT)
    log = _log(pursuit)
    deposit_supplemental(pursuit, "prior-proposal.md", authored_by="firm",
                         log=log, stage="intake")
    lanes = Lanes(firm=firm, pursuit=memory_store(pursuit.root))
    search_log = RunLogger(firm.root, "run_0201", "kb")
    result = card_search(lanes,
                         "how is legacy data converted and reconciled?",
                         log=search_log, stage="path_a_map",
                         agent="kb_mapper")
    returned = [r.kb_id for r in result.results]
    assert any(k.startswith("pkb_") for k in returned)
    assert any(not k.startswith("pkb_") for k in returned)
    line = [r for r in read_run(firm.root / "runs" / "run_0201" /
                                "run.jsonl")
            if r["record_type"] == "kb_retrieval"][-1]
    assert line["kb"]["lanes"] == ["firm", "pursuit"]


def test_stage_run_joins_the_lane_only_where_it_belongs(tmp_path):
    """B75§1c wiring: planning gets the bundle + the header snapshot;
    validation gets the plain store and a bare header; a pursuit with
    EMPTY memory is byte-identical to pre-P17 (plain store, no field)."""
    def make_caller(log):
        return TracedCaller(FakeCaller(ci_script()), log)

    pursuit = _pursuit(tmp_path)
    (pursuit.root / "inbox" / "notes.md").write_text("# SME notes\nfacts.\n")
    deposit_supplemental(pursuit, "notes.md", authored_by="firm",
                         log=_log(pursuit), stage="intake")

    planning = StageRun(pursuit, make_caller, "dry_run", "planning",
                        kb_root=KB_ROOT, extras=_extras)
    assert isinstance(planning.lanes, Lanes)
    assert planning.lanes.pursuit is not None
    header = [r for r in _lines(pursuit, planning.log.run_id)
              if r["record_type"] == "run_start"][-1]
    assert header["run"]["pursuit_kb_snapshot"] == \
        memory_snapshot(pursuit.root)

    validation = StageRun(pursuit, make_caller, "dry_run", "validation",
                          kb_root=KB_ROOT, extras=_extras)
    assert isinstance(validation.lanes, KBStore), \
        "the claim audit's universe stays the firm store alone"
    header = [r for r in _lines(pursuit, validation.log.run_id)
              if r["record_type"] == "run_start"][-1]
    assert "pursuit_kb_snapshot" not in header["run"]

    bare = _pursuit(tmp_path, "pur_bare")
    planning_bare = StageRun(bare, make_caller, "dry_run", "planning",
                             kb_root=KB_ROOT, extras=_extras)
    assert isinstance(planning_bare.lanes, KBStore)
    header = [r for r in read_run(bare.root / "runs" /
                                  planning_bare.log.run_id / "run.jsonl")
              if r["record_type"] == "run_start"][-1]
    assert "pursuit_kb_snapshot" not in header["run"]


def test_fact_shaped_memory_card_never_reaches_the_fact_catalog(tmp_path):
    """The Tier-1 firewall (B75§2), both belts: the fact catalog is
    built from the firm store alone, and even a fact-shaped card smuggled
    straight into the memory store (past the door) never surfaces in any
    lane search — the pre-idf fact_sheet drop is lane-blind."""
    firm, _ = ingest_corpus(tmp_path / "kb")
    pursuit = _pursuit(tmp_path)
    memory = memory_store(pursuit.root)
    memory.write_card(
        {"kb_id": "pkb_smuggledfact", "layer": "fact_sheet",
         "summary": "a fact-shaped pursuit card",
         "owner": "nobody", "verified_date": "2026-08-29"},
        "Smuggled claim text.",
        {"source_pursuit": pursuit.pursuit_id, "authored_by": "buyer"}, {})
    assert all(c["kb_id"] != "pkb_smuggledfact" for c in fact_catalog(firm))
    lanes = Lanes(firm=firm, pursuit=memory)
    log = RunLogger(firm.root, "run_0202", "kb")
    result = card_search(lanes, "smuggled fact-shaped pursuit card",
                         log=log, stage="path_a_map", agent="kb_mapper")
    assert all(not r.kb_id == "pkb_smuggledfact" for r in result.results)
