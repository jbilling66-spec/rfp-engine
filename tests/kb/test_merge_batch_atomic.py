"""P1-21 (P26b-2): merge_batch validates the WHOLE batch before any
write. A refusal at proposal k used to leave 1..k-1 rewritten and marked
accepted with no curation-log line — the record of what changed was
exactly the thing lost. Now: a refusal applies nothing, decides nothing,
logs nothing; a failure INSIDE the apply pass still writes the line
naming what applied and why it stopped."""

import json

import pytest

from engine.kb.curation import CurationRefused, merge_batch, propose_edit
from engine.kb.store import KBStore
from engine.flywheel.proposals import ProposalStore

PROV = {"source_pursuit": "pur_x", "source_client": "Fixture County",
        "date": "2026-01-01", "ingested_by": "ingestion_agent"}
AT = "2026-09-03T10:00:00Z"
IDS = ("kb_alpha0001", "kb_beta00001", "kb_gamma0001")


def _store(root) -> KBStore:
    store = KBStore(root)
    for kb_id, title in zip(IDS, ("A", "B", "C")):
        store.write_card(
            {"kb_id": kb_id, "layer": "corpus", "doc_kind": "section_exemplar",
             "title": title, "summary": f"Summary {title}.",
             "owner": "Delivery Lead"}, f"Body {title}.", PROV, {})
    return store


def _three(store) -> list[str]:
    return [propose_edit(store, kb_id, {"summary": f"Changed {kb_id}."},
                         operator="Sam", at=AT)["proposal_id"]
            for kb_id in IDS]


def _log_lines(store) -> list[dict]:
    log = store.root / "curation-log.jsonl"
    if not log.exists():
        return []
    return [json.loads(l) for l in log.read_text(encoding="utf-8").splitlines()]


def test_a_decided_proposal_mid_batch_refuses_the_whole_batch(tmp_path):
    store = _store(tmp_path / "kb")
    pids = _three(store)
    proposals = ProposalStore(store.root)
    proposals.decide(pids[1], decision="rejected", by="Kim", at=AT)
    snapshot = store.snapshot()
    with pytest.raises(CurationRefused, match="decision is made once"):
        merge_batch(store, pids, operator="Sam", at=AT)
    assert store.snapshot() == snapshot, "nothing applied"
    assert proposals.read(pids[0])["status"] == "proposed", "nothing decided"
    assert proposals.read(pids[2])["status"] == "proposed"
    assert store.read_card(IDS[0])[0]["summary"] == "Summary A."
    assert _log_lines(store) == [], "nothing logged — nothing happened"


def test_a_missing_target_mid_batch_refuses_the_whole_batch(tmp_path):
    store = _store(tmp_path / "kb")
    pids = _three(store)
    store.delete_card(IDS[1])
    snapshot = store.snapshot()
    with pytest.raises(CurationRefused, match="no longer exists"):
        merge_batch(store, pids, operator="Sam", at=AT)
    assert store.snapshot() == snapshot
    assert ProposalStore(store.root).read(pids[0])["status"] == "proposed"
    assert _log_lines(store) == []


def test_a_diff_the_front_matter_cannot_take_is_refused_unwritten(tmp_path):
    """The flywheel's `update_card` carries diff.text (a section's
    before/after prose) and no front-matter field — merge used to write
    `text` into the card header. Refused at validation by name."""
    store = _store(tmp_path / "kb")
    proposal = ProposalStore(store.root).open(
        source={"door": "flywheel", "pursuit_id": "pur_x",
                "event_ids": ["evt_0001"]},
        target="corpus", kind="update_card", at=AT, kb_id=IDS[0],
        diff={"text": {"before": "old prose", "after": "new prose"}})
    good = propose_edit(store, IDS[1], {"summary": "Fine."},
                        operator="Sam", at=AT)["proposal_id"]
    with pytest.raises(CurationRefused, match="does not fit"):
        merge_batch(store, [good, proposal["proposal_id"]],
                    operator="Sam", at=AT)
    card, _ = store.read_card(IDS[0])
    assert "text" not in card
    assert store.read_card(IDS[1])[0]["summary"] == "Summary B."
    assert _log_lines(store) == []


def test_a_failure_inside_the_apply_pass_logs_what_applied(tmp_path,
                                                          monkeypatch):
    store = _store(tmp_path / "kb")
    pids = _three(store)
    original = KBStore.update_card_front
    calls = {"n": 0}

    def flaky(self, kb_id, **fields):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("disk went away")
        return original(self, kb_id, **fields)

    monkeypatch.setattr(KBStore, "update_card_front", flaky)
    with pytest.raises(OSError):
        merge_batch(store, pids, operator="Sam", at=AT)
    lines = _log_lines(store)
    assert len(lines) == 1
    assert lines[0]["proposal_ids"] == [pids[0]], "what applied, by name"
    assert lines[0]["aborted"].startswith("OSError: disk went away")
    assert lines[0]["snapshot_before"] != lines[0]["snapshot_after"]
    proposals = ProposalStore(store.root)
    assert proposals.read(pids[0])["status"] == "accepted"
    assert proposals.read(pids[1])["status"] == "proposed"
    assert proposals.read(pids[2])["status"] == "proposed"


def test_a_clean_batch_still_writes_exactly_one_line(tmp_path):
    store = _store(tmp_path / "kb")
    pids = _three(store)
    line = merge_batch(store, pids, operator="Sam", at=AT)
    assert line["proposal_ids"] == pids
    assert "aborted" not in line
    assert _log_lines(store) == [line]
