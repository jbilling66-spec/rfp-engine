"""Pursuit-memory purge (P17/C7, B69§1's second half): retained by
default, PURGEABLE ON DEMAND — the lane deletes whole, drafts citing
its cards go with it (R8 applied to the lane), the accounting survives
in the pursuit, and the CLEAN verdict scans EVERY remaining lane —
"purged with the pursuit" is proven, not assumed."""

import json

from engine.kb import Lanes, card_search, purge_pursuit_memory
from engine.kb.pursuit_memory import deposit_supplemental, memory_store
from engine.runlog import RunLogger
from engine.workspace import PursuitDir

from tests.kb.fixtures.corpus import ingest_corpus

DOC = """# Prior approach
Legacy ledgers converted in four waves. Marker: PURGEME-TOKEN.
"""


def _seeded_pursuit(tmp_path, pid="pur_purge"):
    pursuit = PursuitDir(tmp_path, pid)
    (pursuit.root / "inbox" / "prior.md").write_text(DOC)
    log = RunLogger(pursuit.root, "run_0001", pid)
    minted = deposit_supplemental(pursuit, "prior.md", authored_by="firm",
                                  log=log, stage="intake")
    return pursuit, minted


def test_purge_deletes_lane_sweeps_drafts_and_proves_it(tmp_path):
    firm, _ = ingest_corpus(tmp_path / "kb")
    pursuit, minted = _seeded_pursuit(tmp_path)
    assert minted
    # A draft citing the memory card — client-derived prose that must
    # not outlive its source (the R8 rule).
    draft = pursuit.root / "drafts" / "draft.json"
    draft.write_text(json.dumps({
        "sections": [{"section_id": "sec-01", "cards_cited": minted}]}))

    report = purge_pursuit_memory(pursuit.root, actor="owner",
                                  firm_store=firm)
    assert sorted(report.purged) == sorted(minted)
    assert report.swept_clean, report.sweep_findings
    assert memory_store(pursuit.root).list_cards() == []
    assert not draft.exists(), "the citing draft goes with the lane"
    assert report.accounting["drafts"], "and is accounted, not silent"
    accounting_file = json.loads(
        open(report.accounting_path, encoding="utf-8").read())
    assert accounting_file["pursuit_memory_cards"] == report.purged
    assert accounting_file["sweep_clean"] is True

    # And retrieval no longer sees the lane's content anywhere.
    log = RunLogger(firm.root, "run_0301", "kb")
    result = card_search(Lanes(firm=firm), "PURGEME-TOKEN waves",
                         log=log, stage="path_a_map", agent="kb_mapper")
    assert all("pkb_" not in r.kb_id for r in result.results)


def test_sweep_catches_a_survivor_in_another_lane(tmp_path):
    """The widened verdict: a purged card's id surviving in ANY lane is
    a finding — the scan is workspace-wide, not store-local."""
    firm, _ = ingest_corpus(tmp_path / "kb")
    pursuit, minted = _seeded_pursuit(tmp_path)
    other, _ = _seeded_pursuit(tmp_path, "pur_other")
    # Smuggle a copy of a purged-id card into the OTHER pursuit's lane.
    survivor = memory_store(other.root)
    survivor.write_card(
        {"kb_id": minted[0], "layer": "corpus",
         "summary": "a copy that should not survive"},
        "copied body", {"source_pursuit": "pur_other",
                        "authored_by": "firm"}, {})

    report = purge_pursuit_memory(pursuit.root, actor="owner",
                                  firm_store=firm)
    assert not report.swept_clean
    assert any(minted[0] in f for f in report.sweep_findings)
