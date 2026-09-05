"""P28 (P1-4, the owner's call): a second reader of independent lineage
proposes identifiers over every ingested document and the union feeds
substitution — both readers must miss for a residue to reach the scan.
The scripted doubles read the answer key; what is proven here is the
union, the wire discipline and the counts, not either model's recall
(that is A1's live run).
"""

import json
from pathlib import Path

import pytest

from engine.kb import KBStore, SourceDoc, ingest_document
from engine.kb.evalset import (default_script, evaluate_anonymization_set,
                               retrievable_text)
from engine.kb.ingest import (REVIEWER_AGENT, build_review_prompt,
                              parse_reviewer_wire)
from engine.llm import FakeCaller, TracedCaller
from engine.runlog import RunLogger

CASES_PATH = Path(__file__).resolve().parents[2] / "evals" / "anonymization" / "cases.json"
CLIENT = "Foxfire Municipal Utilities"
SUB = "Halvorsen Data Systems"
DOC = (f"# DOC:xc_doc\n\n## Data Migration\n\n{CLIENT} engaged us to migrate "
       f"billing data; {SUB} handled the legacy extracts as our subcontractor "
       "and the cutover ran clean.\n")


def _wire(identifiers: list[dict]) -> str:
    return json.dumps({
        "chunk_annotations": [{"chunk": 0, "summary": "Migration body.",
                               "section_types": [], "type_tags": []}],
        "qa_pairs": [], "identifiers": identifiers,
        "client_descriptor": "a municipal utility"})


def _review(identifiers: list[dict]) -> str:
    return json.dumps({"identifiers": identifiers})


def _ingest(tmp_path, script: dict):
    store = KBStore(tmp_path / "kb")
    log = RunLogger(store.root, "run_0001", "kb")
    caller = TracedCaller(FakeCaller(script), log)
    doc = SourceDoc(doc_id="xc_doc", text=DOC, source_client=CLIENT,
                    source_pursuit="pur_xc", outcome="won", date="2026-01-01",
                    authored_by="firm")
    return store, ingest_document(store, caller, log, doc)


def test_the_reviewer_catches_what_the_first_reader_missed(tmp_path):
    store, report = _ingest(tmp_path, {
        "ingestion_agent": _wire([{"value": CLIENT, "type": "CLIENT"}]),
        REVIEWER_AGENT: _review([{"value": CLIENT, "type": "CLIENT"},
                                 {"value": SUB, "type": "ORGANIZATION"}]),
    })
    assert report.status == "ingested", report.findings
    text = " ".join(retrievable_text(store).values())
    assert "halvorsen" not in text
    assert "[organization]" in text
    assert report.cross_check == {"first": 1, "reviewer": 2,
                                  "reviewer_only": 1, "first_only": 0,
                                  "structured": 0}


def test_both_readers_missing_an_unstructured_name_is_the_stated_limit(tmp_path):
    """The code gate scans for what is INDEXED (plus the structured
    classes); a third-party name neither reader lists is not a residue
    the scan can see. Pinned as the limit it is — the labeled eval set
    and A1's live run are the controls on the readers themselves."""
    store, report = _ingest(tmp_path, {
        "ingestion_agent": _wire([{"value": CLIENT, "type": "CLIENT"}]),
        REVIEWER_AGENT: _review([{"value": CLIENT, "type": "CLIENT"}]),
    })
    assert report.status == "ingested"
    assert "halvorsen" in " ".join(retrievable_text(store).values())
    assert report.cross_check["reviewer_only"] == 0


def test_the_reviewer_wire_must_be_json_naming_the_agent(tmp_path):
    with pytest.raises(ValueError, match=REVIEWER_AGENT):
        _ingest(tmp_path, {
            "ingestion_agent": _wire([{"value": CLIENT, "type": "CLIENT"}]),
            # an unscripted FakeCaller echoes "[fake:<agent>] ok"
        })
    with pytest.raises(ValueError, match="lacks an identifiers list"):
        parse_reviewer_wire(json.dumps({"summary": "x"}), "d")


def test_a_reviewer_fallback_never_downgrades_a_typed_entry(tmp_path):
    store, report = _ingest(tmp_path, {
        "ingestion_agent": _wire([{"value": CLIENT, "type": "CLIENT"},
                                  {"value": SUB, "type": "ORGANIZATION"}]),
        REVIEWER_AGENT: _review([{"value": CLIENT, "type": "PERSON"},
                                 {"value": SUB, "type": "VENDOR"}]),
    })
    assert report.status == "ingested"
    text = " ".join(retrievable_text(store).values())
    assert "[client]" in text and "[organization]" in text
    assert "[redacted]" not in text
    cleared = [c for c in report.cleared_facets
               if c["where"] == "reviewer identifiers"]
    assert {c["value"] for c in cleared} == {"PERSON", "VENDOR"}


def test_cross_check_carries_counts_never_values(tmp_path):
    _, report = _ingest(tmp_path, {
        "ingestion_agent": _wire([{"value": CLIENT, "type": "CLIENT"}]),
        REVIEWER_AGENT: _review([{"value": SUB, "type": "ORGANIZATION"}]),
    })
    assert set(report.cross_check) == {"first", "reviewer", "reviewer_only",
                                       "first_only", "structured"}
    assert all(isinstance(v, int) for v in report.cross_check.values())
    assert report.cross_check["first_only"] == 1


def test_the_review_prompt_is_starved_to_text_and_types():
    from engine.kb.canonical import elements_from_markdown
    prompt = build_review_prompt("xc_doc", elements_from_markdown(DOC))
    assert prompt.startswith("# DOC:xc_doc")
    assert SUB in prompt and "Identifier types: CLIENT" in prompt
    for absent in ("Allowed section_types", "Allowed type_tags", "<<CHUNK",
                   "descriptor", "summary"):
        assert absent not in prompt, absent


def test_one_sabotaged_reader_is_repaired_by_the_union(tmp_path):
    """The twin of test_sabotaged_extraction_caught_by_eval_not_code_scan:
    the first reader stops reporting fees, the reviewer does not — the
    union substitutes them and the labeled suite passes."""
    def first_drops_fees(meta):
        honest = default_script(meta)

        def respond(prompt: str) -> str:
            wire = json.loads(honest["ingestion_agent"](prompt))
            wire["identifiers"] = [
                i for i in wire["identifiers"] if i["type"] != "FEE"]
            return json.dumps(wire)

        return {"ingestion_agent": respond,
                REVIEWER_AGENT: honest[REVIEWER_AGENT]}

    result, failures = evaluate_anonymization_set(
        CASES_PATH, tmp_path, script_factory=first_drops_fees)
    assert failures == []
    assert result is True
