"""C10/P12, extended at P13/C8 — the ROADMAP P12 acceptance clause by
name: degraded extraction still ingests, flagged. The spec's rule
(EXTRACTION_AND_SCALE_SPEC §A5): content is never held back pending
better parsing. Since P13/C8 the card CARRIES extraction_status — B51's
record-only deferral, deliberately flipped here with its readers."""

import dataclasses
import json

from engine.kb import KBStore, SourceDoc, ingest_document
from engine.llm import FakeCaller, TracedCaller
from engine.runlog import RunLogger
from tests.kb.fixtures.corpus import SCRIPT, SOURCE_DOCS


def _run_log(store):
    run_dir = next((store.root / "runs").iterdir())
    return [json.loads(line) for line in
            (run_dir / "run.jsonl").read_text().splitlines()]


def _ingest(tmp_path, doc):
    store = KBStore(tmp_path / "kb")
    log = RunLogger(store.root, "run_0001", "kb")
    caller = TracedCaller(FakeCaller(SCRIPT), log)
    return store, ingest_document(store, caller, log, doc)


def test_degraded_extraction_still_ingests_flagged(tmp_path):
    degraded = dataclasses.replace(
        SOURCE_DOCS[0], extractor="python-docx", extraction_degraded=True
    )
    store, report = _ingest(tmp_path, degraded)
    # Still ingests — cards written, nothing held back.
    assert report.status == "ingested"
    assert report.cards_written
    # Flagged — on the report and in the run log.
    assert report.extraction_flagged is True
    validations = [r["validation"] for r in _run_log(store)
                   if r["record_type"] == "validation"]
    assert {"check": "extraction", "result": "flag"} in validations
    # P13 (B51 deferral closed): the card carries extraction_status, and
    # a degraded card is STILL retrievable — flag, never gate.
    for kb_id in report.cards_written:
        card, _body = store.read_card(kb_id)
        assert card["extraction_status"] == "degraded"
        assert "extraction_flagged" not in card  # report field, never card


def test_clean_extraction_passes_not_flags(tmp_path):
    store, report = _ingest(tmp_path, SOURCE_DOCS[0])
    assert report.status == "ingested"
    assert report.extraction_flagged is False
    validations = [r["validation"] for r in _run_log(store)
                   if r["record_type"] == "validation"]
    assert {"check": "extraction", "result": "pass"} in validations
    assert {"check": "extraction", "result": "flag"} not in validations
    for kb_id in report.cards_written:
        card, _body = store.read_card(kb_id)
        assert card["extraction_status"] == "clean"
