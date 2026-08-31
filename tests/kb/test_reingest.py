"""C9 (P13) — the ROADMAP clause by name: re-ingest preserves card ids +
edit_survival and emits the created/matched/drifted/orphaned
reconciliation report. Orphans are retained and reviewable (R6)."""

import json

from engine.kb import KBStore, SourceDoc, ingest_document
from engine.kb.curation import orphans_view
from engine.llm import FakeCaller, TracedCaller
from engine.runlog import RunLogger

CLIENT = "Foxfire Analytics"

ALPHA = ("Our approach pairs a fixed-scope discovery with weekly "
         "steering checkpoints, and every deliverable carries a named "
         "owner and an acceptance test agreed before work begins.")
BETA = ("The delivery team is five consultants: a lead, two functional "
        "analysts, a data engineer, and a trainer, each dedicated at "
        "least half time for the full engagement.")
BETA_EDITED = ("The delivery team is six consultants: a lead, two "
               "functional analysts, a data engineer, a trainer, and a "
               "tester, each dedicated at least half time for the full "
               "engagement.")
GAMMA = ("Quality gates run at the end of every build week, and no "
         "workstream advances with an open severity-one defect.")


def _doc_text(*sections: tuple[str, str]) -> str:
    parts = ["# DOC:tw_doc", ""]
    for title, body in sections:
        parts += [f"## {title}", "", body, ""]
    return "\n".join(parts)


def _wire(n_chunks: int) -> str:
    annotations = [
        {"chunk": i, "summary": f"Annotated summary for chunk {i}.",
         "section_types": [], "type_tags": []}
        for i in range(n_chunks)
    ]
    return json.dumps({
        "chunk_annotations": annotations,
        "qa_pairs": [],
        "identifiers": [],
        "client_descriptor": "a synthetic analytics firm",
    })


def _ingest(store, text: str, n_chunks: int, run: str):
    log = RunLogger(store.root, run, "kb")
    caller = TracedCaller(
        FakeCaller({"ingestion_agent": _wire(n_chunks)}), log)
    doc = SourceDoc(
        doc_id="tw_doc", text=text, source_client=CLIENT,
        source_pursuit="pur_tw_2026", outcome="won", date="2026-08-01",
        authored_by="firm", known_identifiers={CLIENT: "CLIENT"},
    )
    return ingest_document(store, caller, log, doc)


def test_first_ingest_has_no_reconciliation(tmp_path):
    store = KBStore(tmp_path / "kb")
    report = _ingest(store, _doc_text(("Alpha", ALPHA), ("Beta", BETA)),
                     2, "run_0001")
    assert report.status == "ingested"
    assert report.reconciliation is None


def test_identical_reingest_all_matched(tmp_path):
    store = KBStore(tmp_path / "kb")
    text = _doc_text(("Alpha", ALPHA), ("Beta", BETA))
    first = _ingest(store, text, 2, "run_0001")
    before = {p.name: p.read_bytes()
              for p in (store.root / "cards").glob("*.md")}
    second = _ingest(store, text, 2, "run_0002")
    assert second.cards_written == []
    assert second.reconciliation == {
        "created": 0, "matched": len(first.cards_written),
        "drifted": 0, "orphaned": 0}
    after = {p.name: p.read_bytes()
             for p in (store.root / "cards").glob("*.md")}
    assert before == after
    reports = list((store.root / "reconciliation").glob("*.json"))
    assert len(reports) == 1  # content-addressed name: rerun overwrites


def test_edited_reingest_drifts_keeps_id_and_history(tmp_path):
    store = KBStore(tmp_path / "kb")
    first = _ingest(store, _doc_text(("Alpha", ALPHA), ("Beta", BETA)),
                    2, "run_0001")
    beta_id = [k for k in first.cards_written
               if "six" not in store.read_card(k)[1]
               and "five" in store.read_card(k)[1]][0]
    store.update_card_front(beta_id, edit_survival=0.83)

    second = _ingest(store,
                     _doc_text(("Alpha", ALPHA), ("Beta", BETA_EDITED)),
                     2, "run_0002")
    assert second.reconciliation == {
        "created": 0, "matched": 1, "drifted": 1, "orphaned": 0}
    card, body = store.read_card(beta_id)
    # The id never changed; the content did; the history survived.
    assert "six consultants" in body
    assert card["version"] == 2
    assert card["edit_survival"] == 0.83
    assert card["identity"]["matched_from"] == beta_id
    assert 0 < card["identity"]["drift"] < 0.3
    # The NEW canonical model's backref points at the KEPT id.
    recon = json.loads(next(
        (store.root / "reconciliation").glob("*.json")).read_text())
    new_model = json.loads(
        (store.root / "canonical"
         / f"{recon['canonical_doc_id']}.json").read_text())
    assert beta_id in {c.get("kb_id") for c in new_model["chunks"]}
    # And the drifted card's restricted record gained the new source.
    prov = json.loads(
        (store.root / "restricted" / "provenance"
         / f"{beta_id}.json").read_text())
    assert any(s["source_pursuit"] == "pur_tw_2026" for s in prov["sources"])


def test_removed_section_orphans_card_retained(tmp_path):
    store = KBStore(tmp_path / "kb")
    first = _ingest(store, _doc_text(("Alpha", ALPHA), ("Beta", BETA)),
                    2, "run_0001")
    second = _ingest(store, _doc_text(("Alpha", ALPHA)), 1, "run_0002")
    assert second.reconciliation == {
        "created": 0, "matched": 1, "drifted": 0, "orphaned": 1}
    orphan_id = [k for k in first.cards_written
                 if "five consultants" in store.read_card(k)[1]][0]
    assert store.card_exists(orphan_id), "orphans are reviewed, not dropped"
    queue = orphans_view(store)
    assert [row["kb_id"] for row in queue] == [orphan_id]
    assert queue[0]["doc_id"] == "tw_doc"


def test_added_section_creates(tmp_path):
    store = KBStore(tmp_path / "kb")
    _ingest(store, _doc_text(("Alpha", ALPHA), ("Beta", BETA)),
            2, "run_0001")
    second = _ingest(store,
                     _doc_text(("Alpha", ALPHA), ("Beta", BETA),
                               ("Gamma", GAMMA)),
                     3, "run_0002")
    assert second.reconciliation == {
        "created": 1, "matched": 2, "drifted": 0, "orphaned": 0}
    assert len(second.cards_written) == 1
    _card, body = store.read_card(second.cards_written[0])
    assert "Quality gates" in body


def test_reconciliation_report_is_deterministic_bytes(tmp_path):
    """Kill/resume discipline: the persisted report carries no clock and
    a content-addressed name — the same sequence in two directories
    writes byte-identical reports (the C3 cross-directory pattern)."""
    text_v1 = _doc_text(("Alpha", ALPHA), ("Beta", BETA))
    text_v2 = _doc_text(("Alpha", ALPHA), ("Beta", BETA_EDITED))
    contents = []
    for sub in ("one", "two"):
        store = KBStore(tmp_path / sub / "kb")
        _ingest(store, text_v1, 2, "run_0001")
        _ingest(store, text_v2, 2, "run_0002")
        path = next((store.root / "reconciliation").glob("*.json"))
        contents.append((path.name, path.read_bytes()))
    assert contents[0] == contents[1]