"""P34a (B155 §2): a dry run computes the real run's report — writes,
merges, skips, proposals, reconciliation — and writes nothing to the store
but its run record and the access-log lines of its reads. One writer seam,
two implementations, one control flow; the in-call mirror (`written_now`,
`deleted_now`) keeps the dry answer equal to the real one when two
candidates in one document share a body. Bodies and their derived scores
follow tests/kb/test_b15_tiebreak.py (fwd 0.77 / rev 0.94 for the
variant; fwd 0.83 / rev 1.0 for the extension).
"""

import hashlib
import json

from engine.kb import KBStore, SourceDoc, ingest_document
from engine.kb.identity import kb_id_for
from engine.llm import FakeCaller, TracedCaller
from engine.runlog import RunLogger, read_run
from tests.kb.fixtures.corpus import REVIEWER_NONE

BODY = ("The migration factory converts legacy balances wave by wave "
        "with penny-level reconciliation against the source ledger.")
BODY_VARIANT = ("The migration factory converts legacy balances wave by "
                "wave with cent-level reconciliation against the source "
                "ledger.")
BODY_EXTENDED = ("The migration factory converts legacy balances wave by "
                 "wave with penny-level reconciliation against the source "
                 "ledger. Reconciliation runs wave by wave against the "
                 "source ledger.")
BODY_NEW = ("Hypercare runs for six weeks after go-live with a named lead "
            "on every shift and a defect triage each morning.")
CLAIM = "Hypercare runs for six weeks after go-live."


def _wire(n: int, *, claim_on: int | None = None) -> str:
    return json.dumps({
        "chunk_annotations": [
            {"chunk": i, "summary": "Migration approach exemplar.",
             "section_types": ["data_migration"],
             "type_tags": ["data_migration"],
             **({"claim_candidates": [CLAIM]} if i == claim_on else {})}
            for i in range(n)],
        "qa_pairs": [], "identifiers": [],
        "client_descriptor": "a synthetic firm",
    })


def _text(doc_id: str, bodies: list[str]) -> str:
    # One heading per body, the SAME heading each time, so every chunk is
    # titled alike and the b15 score derivations hold.
    sections = "\n\n".join(f"## Data Migration\n\n{b}" for b in bodies)
    return f"# DOC:{doc_id}\n\n{sections}\n"


def _ingest(store, doc_id, bodies, run, *, dry_run=False, claim_on=None):
    log = RunLogger(store.root, run, "kb")
    caller = TracedCaller(FakeCaller({
        "ingestion_agent": _wire(len(bodies), claim_on=claim_on),
        **REVIEWER_NONE}), log)
    doc = SourceDoc(
        doc_id=doc_id, text=_text(doc_id, bodies),
        source_client="Foxfire", source_pursuit=f"pur_{doc_id}",
        outcome="won", date="2026-08-01", authored_by="firm",
        known_identifiers={"Foxfire": "CLIENT"})
    return ingest_document(store, caller, log, doc, dry_run=dry_run)


def _snapshot(root) -> dict[str, str]:
    """Every store byte except the run records and the access log — the
    two traces a dry run is allowed to leave (B155 §3b)."""
    out = {}
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        if rel.startswith("runs/") or rel == "restricted/access.jsonl":
            continue
        out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def _access_lines(root) -> list[dict]:
    path = root / "restricted" / "access.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _ids(store) -> list[str]:
    return sorted(c["kb_id"] for c in store.list_cards())


def _report_view(report) -> dict:
    return {"status": report.status, "cards_written": report.cards_written,
            "merged": report.merged, "skipped": report.skipped,
            "proposals": report.proposals,
            "reconciliation": report.reconciliation}


def test_dry_run_leaves_the_store_bytes_untouched(tmp_path):
    store = KBStore(tmp_path / "kb")
    first = _ingest(store, "doc_a", [BODY], "run_0001")
    assert first.cards_written == [kb_id_for(BODY)] and not first.dry_run
    before = _snapshot(store.root)
    access_before = len(_access_lines(store.root))

    report = _ingest(store, "doc_b", [BODY, BODY_VARIANT, BODY_NEW],
                     "run_0002", dry_run=True, claim_on=2)

    assert report.dry_run and report.status == "ingested"
    assert report.skipped == [kb_id_for(BODY)]          # exact duplicate
    assert [m["absorbed"] for m in report.merged] in (   # near duplicate
        [kb_id_for(BODY_VARIANT)], [kb_id_for(BODY)])
    assert kb_id_for(BODY_NEW) in report.cards_written
    assert len(report.proposals) == 1
    assert report.proposals[0].startswith("prop_")
    # the store: byte-identical outside the two permitted traces
    assert _snapshot(store.root) == before
    assert _ids(store) == [kb_id_for(BODY)]
    assert not list(store.root.glob("proposals/*.json"))
    # the permitted traces: the reads behind the boundary are logged as
    # ingest reads, and the run record carries the retrieval evidence
    new_access = _access_lines(store.root)[access_before:]
    assert new_access and all(
        line["granted"] and line["purpose"] == "ingest" for line in new_access)
    records = read_run(store.root / "runs" / "run_0002" / "run.jsonl")
    kinds = [r["record_type"] for r in records]
    assert kinds.count("agent_call") == 2 and "kb_retrieval" in kinds


def test_dry_run_predicts_the_real_run(tmp_path):
    """Doc B: the extension (the new card survives, A's is deleted), A's
    body again (found through the absorbed fold onto the card this call
    wrote), a new body, the same new body again (an in-document duplicate
    — written once, skipped once). Every leg leans on the in-call mirror."""
    store = KBStore(tmp_path / "kb")
    _ingest(store, "doc_a", [BODY], "run_0001")
    bodies = [BODY_EXTENDED, BODY, BODY_NEW, BODY_NEW]

    dry = _ingest(store, "doc_b", bodies, "run_0002", dry_run=True)
    assert _ids(store) == [kb_id_for(BODY)]      # still untouched
    real = _ingest(store, "doc_b", bodies, "run_0003")

    assert dry.dry_run and not real.dry_run
    assert _report_view(dry) == _report_view(real)
    # and the real run did what both reports say
    ext, new, old = kb_id_for(BODY_EXTENDED), kb_id_for(BODY_NEW), kb_id_for(BODY)
    assert real.cards_written == [ext, new]
    assert real.skipped == [new]
    assert [(m["survivor"], m["absorbed"], m.get("prior", False))
            for m in real.merged] == [(ext, old, False), (ext, old, True)]
    assert _ids(store) == sorted([ext, new])


def test_dry_run_of_a_reingest_reports_drift_and_rewrites_nothing(tmp_path):
    store = KBStore(tmp_path / "kb")
    _ingest(store, "doc_a", [BODY], "run_0001")
    card_path = store.root / "cards" / f"{kb_id_for(BODY)}.md"
    bytes_before = card_path.read_bytes()

    dry = _ingest(store, "doc_a", [BODY_VARIANT], "run_0002", dry_run=True)
    assert dry.reconciliation == {"created": 0, "matched": 0,
                                  "drifted": 1, "orphaned": 0}
    assert dry.cards_written == [] and dry.merged == []
    assert card_path.read_bytes() == bytes_before      # not rewritten
    assert _ids(store) == [kb_id_for(BODY)]

    real = _ingest(store, "doc_a", [BODY_VARIANT], "run_0003")
    assert real.reconciliation == dry.reconciliation
    assert card_path.read_bytes() != bytes_before      # rewritten in place
    card, body = store.read_card(kb_id_for(BODY))
    assert body.strip() == BODY_VARIANT and card["version"] == 2
