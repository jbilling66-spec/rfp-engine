"""P1-40 (P26b-2): the firm KB has mutual exclusion — two stewards
merging the same proposal at once end with ONE acceptance, ONE curation-
log line, one decided block; two different KB roots never block each
other; merge -> decide nests without deadlock.

The race is FORCED, not hoped for: the store's write door parks on an
event the test releases only after both threads are in flight, so the
interleaving that used to lie is the one exercised. Run against the
pre-lock tree this test is red (two log lines, zero refusals)."""

import json
import threading

import pytest

from engine.kb.curation import CurationRefused, merge_batch, propose_edit
from engine.kb.store import KBStore
from engine.flywheel.proposals import ProposalStore

PROV = {"source_pursuit": "pur_x", "source_client": "Fixture County",
        "date": "2026-01-01", "ingested_by": "ingestion_agent"}
AT = "2026-09-03T10:00:00Z"


def _seed(root) -> str:
    store = KBStore(root)
    store.write_card(
        {"kb_id": "kb_alpha0001", "layer": "corpus",
         "doc_kind": "section_exemplar", "title": "Data Migration Approach",
         "summary": "Seven mock conversions.", "owner": "Delivery Lead"},
        "Body one.", PROV, {})
    proposal = propose_edit(store, "kb_alpha0001", {"summary": "Eight."},
                            operator="Sam Steward", at=AT)
    return proposal["proposal_id"]


class _ParkingStore(KBStore):
    """A store whose front-matter write parks until released — the
    window between 'status is proposed' and 'status is accepted' held
    open on purpose."""

    def __init__(self, root, *, entered: threading.Event,
                 release: threading.Event):
        super().__init__(root)
        self._entered = entered
        self._release = release

    def update_card_front(self, kb_id, **fields):
        self._entered.set()
        assert self._release.wait(timeout=10), "the test never released"
        return super().update_card_front(kb_id, **fields)


def test_two_threads_racing_one_proposal_accept_it_once(tmp_path):
    root = tmp_path / "kb"
    pid = _seed(root)
    entered, release = threading.Event(), threading.Event()
    outcomes: dict[str, object] = {}

    def run(name):
        # Two stores on one root — the shape of two web requests.
        store = _ParkingStore(root, entered=entered, release=release)
        try:
            outcomes[name] = merge_batch(store, [pid], operator=name, at=AT)
        except CurationRefused as refusal:
            outcomes[name] = refusal

    first = threading.Thread(target=run, args=("Sam Steward",))
    second = threading.Thread(target=run, args=("Kim Steward",))
    first.start()
    assert entered.wait(timeout=10), "the first merge never reached the write"
    second.start()
    second.join(timeout=0.5)  # the second is now blocked (or racing)
    release.set()
    first.join(timeout=10)
    second.join(timeout=10)
    assert not first.is_alive() and not second.is_alive()

    lines = [o for o in outcomes.values() if isinstance(o, dict)]
    refusals = [o for o in outcomes.values() if isinstance(o, CurationRefused)]
    assert len(lines) == 1, outcomes
    assert len(refusals) == 1 and "decision is made once" in str(refusals[0])
    log = root / "curation-log.jsonl"
    assert len(log.read_text(encoding="utf-8").splitlines()) == 1
    proposal = ProposalStore(root).read(pid)
    assert proposal["status"] == "accepted"
    assert proposal["decided"]["by"] == lines[0]["by"]
    card, _ = KBStore(root).read_card("kb_alpha0001")
    assert card["summary"] == "Eight."


def test_the_lock_is_keyed_per_root(tmp_path):
    """Two firms, two roots: a global lock would serialize them and the
    barrier below would time out."""
    roots = [tmp_path / "kb_one", tmp_path / "kb_two"]
    pids = [_seed(root) for root in roots]
    barrier = threading.Barrier(2, timeout=5)
    errors: list[BaseException] = []

    class _MeetingStore(KBStore):
        def update_card_front(self, kb_id, **fields):
            barrier.wait()  # both writes must be in flight at once
            return super().update_card_front(kb_id, **fields)

    def run(root, pid):
        try:
            merge_batch(_MeetingStore(root), [pid], operator="Sam", at=AT)
        except BaseException as exc:  # noqa: BLE001 — surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(r, p))
               for r, p in zip(roots, pids)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert errors == [], errors
    for root, pid in zip(roots, pids):
        assert ProposalStore(root).read(pid)["status"] == "accepted"


def test_merge_and_decide_nest_without_deadlock(tmp_path):
    """merge_batch holds the root's lock and decides through the
    proposal store, which takes the same lock — re-entrant by design."""
    root = tmp_path / "kb"
    store = KBStore(root)
    store.write_card(
        {"kb_id": "kb_alpha0001", "layer": "corpus",
         "doc_kind": "section_exemplar", "title": "A", "summary": "One.",
         "owner": "Delivery Lead"}, "Body.", PROV, {})
    store.write_card(
        {"kb_id": "kb_beta00001", "layer": "corpus",
         "doc_kind": "section_exemplar", "title": "B", "summary": "Two.",
         "owner": "Delivery Lead"}, "Body.", PROV, {})
    pids = [propose_edit(store, kb_id, {"summary": "Changed."},
                         operator="Sam", at=AT)["proposal_id"]
            for kb_id in ("kb_alpha0001", "kb_beta00001")]
    done = threading.Event()
    result: dict = {}

    def run():
        result["line"] = merge_batch(store, pids, operator="Sam", at=AT)
        done.set()

    threading.Thread(target=run, daemon=True).start()
    assert done.wait(timeout=10), "merge_batch deadlocked on its own lock"
    assert sorted(result["line"]["proposal_ids"]) == sorted(pids)
    assert all(ProposalStore(root).read(p)["status"] == "accepted"
               for p in pids)
