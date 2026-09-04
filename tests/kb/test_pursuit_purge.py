"""Pursuit-memory purge (P17/C7, B69§1's second half): retained by
default, PURGEABLE ON DEMAND — the lane deletes whole, drafts citing
its cards go with it (R8 applied to the lane), the accounting survives
in the pursuit, and the CLEAN verdict scans EVERY remaining lane —
"purged with the pursuit" is proven, not assumed."""

import json

from engine.flywheel.proposals import ProposalStore
from engine.kb import Lanes, card_search, purge_pursuit_memory
from engine.kb.curation import merge_batch
from engine.kb.purge import post_purge_sweep
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


# ------------------------------------------------ P1-13: the empty lane

def test_empty_memory_lane_purge_still_answers_to_the_gate(tmp_path):
    """P1-13 (P26b-2): a pursuit with no memory cards skipped the gate."""
    import pytest
    from engine.kb.provenance import ProvenanceAccessDenied

    pursuit = PursuitDir(tmp_path, "pur_empty")
    with pytest.raises(ProvenanceAccessDenied):
        purge_pursuit_memory(pursuit.root, actor="Intruder")
    log = pursuit.root / "memory" / "restricted" / "access.jsonl"
    lines = [json.loads(l) for l in log.read_text(encoding="utf-8").splitlines()]
    assert lines[-1] == {**lines[-1], "actor": "Intruder", "granted": False,
                         "action": "delete", "purpose": "purge"}
    report = purge_pursuit_memory(pursuit.root, actor="owner")
    assert report.purged == []
    assert report.accounting["pursuit_memory_cards"] == []


def test_memory_purge_accounting_guard_fires(tmp_path, monkeypatch):
    """A card delete that silently did nothing is caught by the
    post-delete scan, never reported as purged."""
    import pytest
    from engine.kb.store import KBStore

    firm, _ = ingest_corpus(tmp_path / "kb")
    pursuit, minted = _seeded_pursuit(tmp_path)
    monkeypatch.setattr(KBStore, "delete_card", lambda self, kb_id: None)
    with pytest.raises(RuntimeError, match="left card\\(s\\) in place"):
        purge_pursuit_memory(pursuit.root, actor="owner", firm_store=firm)


# ------------------------------------ P26c: D1 at the carry-forward layer

AT = "2026-09-04T10:00:00Z"


def _flywheel_proposal(firm, pursuit_id, kb_id=None, *, event="evt_0001",
                       text="four waves became five", kind="update_card",
                       target="corpus"):
    return ProposalStore(firm.root).open(
        source={"door": "flywheel", "pursuit_id": pursuit_id,
                "event_ids": [event]},
        target=target, kind=kind, at=AT, kb_id=kb_id,
        diff={"text": {"before": "four waves", "after": text}},
        note=f"from {pursuit_id}")


def test_a_pursuit_purge_strips_its_proposals_and_lessons(tmp_path):
    """What the pursuit taught the firm KB goes with it: its proposals
    (decided or not) are removed, the lessons they landed on firm cards
    are stripped, both are accounted and re-read from disk; another
    pursuit's lesson on the same card stays."""
    firm, _ = ingest_corpus(tmp_path / "kb")
    pursuit, minted = _seeded_pursuit(tmp_path)
    kb_id = firm.list_cards()[0]["kb_id"]
    accepted = _flywheel_proposal(firm, pursuit.pursuit_id, kb_id)
    theirs = _flywheel_proposal(firm, "pur_other", kb_id, event="evt_0009",
                                text="kept lesson")
    merge_batch(firm, [accepted["proposal_id"], theirs["proposal_id"]],
                operator="Sam", at=AT)
    pending = _flywheel_proposal(firm, pursuit.pursuit_id, event="evt_0002",
                                 kind="playbook_note", target="playbook")
    assert len(firm.read_card(kb_id)[0]["lessons"]) == 2

    report = purge_pursuit_memory(pursuit.root, actor="owner",
                                  firm_store=firm)
    assert report.swept_clean, report.sweep_findings
    assert report.accounting["proposals"] == sorted(
        [accepted["proposal_id"], pending["proposal_id"]])
    assert report.accounting["lessons"] == [
        {"kb_id": kb_id, "proposal_id": accepted["proposal_id"]}]
    lessons = firm.read_card(kb_id)[0]["lessons"]
    assert [l["proposal_id"] for l in lessons] == [theirs["proposal_id"]]
    assert [p["proposal_id"] for p in ProposalStore(firm.root).list()] == [
        theirs["proposal_id"]]
    accounting_file = json.loads(
        open(report.accounting_path, encoding="utf-8").read())
    assert accounting_file["proposals"] == report.accounting["proposals"]
    assert accounting_file["lessons"] == report.accounting["lessons"]


def test_the_sweep_sees_a_lesson_and_a_proposal(tmp_path):
    """The CLEAN verdict is only as wide as the scan: a purged identifier
    surviving in a lesson on a card, or in a proposal a steward will
    read, is a finding."""
    firm, _ = ingest_corpus(tmp_path / "kb")
    kb_id = firm.list_cards()[0]["kb_id"]
    firm.update_card_front(kb_id, lessons=[{
        "at": AT, "by": "Sam", "proposal_id": "prop_0123456789ab",
        "after": "PURGEME-TOKEN was the marker."}])
    ProposalStore(firm.root).open(
        source={"door": "flywheel", "pursuit_id": "pur_z"},
        target="playbook", kind="playbook_note", at=AT,
        diff={"comment": {"after": "Say PURGEME-TOKEN plainly."}})
    findings = post_purge_sweep(firm, ["PURGEME-TOKEN"], [])
    where = " ".join(str(f) for f in findings)
    assert kb_id in where and "proposal:prop_" in where
