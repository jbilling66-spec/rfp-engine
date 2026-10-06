"""P29a step a1 (P1-47, P1-48): every string the ingest persists is in the
scan set by construction, and no firm-store record carries the source
FILENAME.

P1-47: the CLI door names the document by a neutral handle; the proposal
note and the run-log refusal line carry the canonical id; the original
filename rides only the restricted meta (behind the access log).
P1-48: question_forms join the scan set (and the card's
placeholders_used) instead of being substituted and forgotten.
"""

import json
from pathlib import Path

from engine.cli.main import main
from engine.kb import KBStore, SourceDoc, ingest_document
from engine.kb.canonical import Element
from engine.llm import FakeCaller, TracedCaller
from engine.runlog import RunLogger


CLIENT = "Foxfire Municipal Utilities"
STEM_TOKEN = "Foxfire"  # the client's distinctive token, in the filename
DOC = ("# DOC:scan_set\n\n## Data Migration\n\nFoxfire Municipal Utilities "
       "engaged us to migrate billing data; the cutover ran clean with "
       "zero rollbacks.\n")
WIRE = json.dumps({
    "chunk_annotations": [{"chunk": 0, "summary": "Migration exemplar.",
                           "section_types": [], "type_tags": [],
                           "claim_candidates": [
                               "Migrated billing data with zero rollbacks."]}],
    "qa_pairs": [], "identifiers": [{"value": CLIENT, "type": "CLIENT"}],
    "client_descriptor": "a municipal utility"})
REVIEW = json.dumps({"identifiers": [{"value": CLIENT, "type": "CLIENT"}]})


def _cli(tmp_path, filename: str, *extra) -> int:
    doc = tmp_path / filename
    doc.write_text(DOC, encoding="utf-8")
    wire = tmp_path / "wire.json"
    wire.write_text(WIRE, encoding="utf-8")
    review = tmp_path / "review.json"
    review.write_text(REVIEW, encoding="utf-8")
    return main(["kb", "ingest", "--kb", str(tmp_path / "kb"),
                 "--file", str(doc), "--client", CLIENT, "--pursuit",
                 "pur_scan", "--date", "2026-01-01", "--wire", str(wire),
                 "--reviewer-wire", str(review), *extra])


def _texts_under(root: Path, pattern: str) -> str:
    return " ".join(p.read_text(encoding="utf-8")
                    for p in root.rglob(pattern) if p.is_file())


def test_the_cli_door_never_persists_the_filename_in_the_firm_store(tmp_path):
    """A source file named after the client: rc 0, and neither the
    proposal note nor the run log carries the stem — the record that
    P1-47 found leaking verbatim."""
    assert _cli(tmp_path, f"{CLIENT} proposal 2025.md") == 0
    kb = tmp_path / "kb"
    proposals = _texts_under(kb / "proposals", "*.json")
    assert proposals, "the claim candidate must open a proposal"
    assert STEM_TOKEN not in proposals
    assert "Claim candidate from cd_" in proposals  # the canonical id, by name
    runs = _texts_under(kb / "runs", "*.jsonl")
    assert STEM_TOKEN not in runs
    # The original filename is retained where the audit human can find
    # it — the restricted meta, behind the access log — and nowhere else.
    metas = _texts_under(kb / "restricted", "*.json")
    assert f"{CLIENT} proposal 2025.md" in metas


def test_the_buyer_authored_refusal_line_carries_the_neutral_handle(tmp_path):
    assert _cli(tmp_path, f"{CLIENT} rfp.md", "--authored-by", "buyer") == 1
    runs = _texts_under(tmp_path / "kb" / "runs", "*.jsonl")
    assert "buyer_authored_source" in runs
    assert STEM_TOKEN not in runs


CLEAN_BODY = ("The engagement migrated billing data; the cutover ran "
              "clean with zero rollbacks.")


def _ingest(tmp_path, questioner, body: str | None = None):
    """body=None names the client in the text; a CLEAN_BODY names nobody,
    so a placeholder can only come from the questioner's forms."""
    store = KBStore(tmp_path / "kb")
    log = RunLogger(store.root, "run_0001", "kb")
    caller = TracedCaller(FakeCaller({"ingestion_agent": WIRE,
                                      "anonymization_reviewer": REVIEW}), log)
    paragraph = body or ("Foxfire Municipal Utilities engaged us to migrate "
                         "billing data; the cutover ran clean with zero "
                         "rollbacks.")
    doc = SourceDoc(doc_id="scan_set", text=f"# DOC:scan_set\n\n{paragraph}\n",
                    source_client=CLIENT,
                    source_pursuit="pur_scan", outcome="won",
                    date="2026-01-01", authored_by="firm",
                    known_identifiers={CLIENT: "CLIENT"},
                    elements=[
                        Element(kind="heading", text="Data Migration", level=2),
                        Element(kind="paragraph", text=paragraph)])
    return store, ingest_document(store, caller, log, doc,
                                  questioner=questioner)


def test_question_forms_are_scanned_not_only_substituted(tmp_path):
    """The questioner writes an acronym and a partial name — spellings
    substitution never touches and the scan is built to catch."""
    def questioner(model):
        return {i: ["what did FMU rehearse before cutover?",
                    "how long was Foxfire's hypercare?"]
                for i in range(len(model.chunks))}
    store, report = _ingest(tmp_path, questioner)
    assert report.status == "blocked"
    assert any(":form:" in f.location for f in report.findings), \
        [f.location for f in report.findings]
    assert store.list_cards() == []


def test_a_substituted_form_counts_in_placeholders_used(tmp_path):
    def questioner(model):
        return {i: [f"what did {CLIENT} rehearse before cutover?"]
                for i in range(len(model.chunks))}
    store, report = _ingest(tmp_path, questioner, body=CLEAN_BODY)
    assert report.status == "ingested", report.findings
    card = store.read_card(report.cards_written[0])[0]
    assert card["question_forms"] == ["what did [CLIENT] rehearse before cutover?"]
    assert "[CLIENT]" not in card["summary"] + card["title"]
    assert "[CLIENT]" in card["anonymization"]["placeholders_used"]


def test_the_scan_set_is_every_persisted_string(tmp_path, monkeypatch):
    """Structural: the gate scans one set built by one helper, and that
    set names every kind of string the ingest writes — elements, claims,
    card title/summary/body, question forms, the proposal note."""
    import engine.kb.ingest as ingest_mod
    seen = {}
    real = ingest_mod.scan

    def spy(texts, identifiers):
        seen.update(texts)
        return real(texts, identifiers)
    monkeypatch.setattr(ingest_mod, "scan", spy)
    _, report = _ingest(tmp_path, lambda model: {0: ["what was migrated?"]})
    assert report.status == "ingested", report.findings
    kinds = {k.split(":")[-2] if k.count(":") >= 2 else k.split(":")[-1]
             for k in seen}
    assert {"element", "title", "summary", "body", "form", "note"} <= kinds, kinds
    assert any(k.startswith("claim:") for k in seen)
