"""The egress gate's scanner (P32a, A6's pre-export leakage scan): the
report names locations, classes and counts and never a value; an
indexed identifier blocks; a structured class is counted, not blocking
(the owner's call, 2026-10-04); the pursuit's own buyer and the firm are
never residue; the universe is the restricted index read under the
engine's grant."""

import json

import pytest

from engine.assembly.egress import (
    CHECK,
    EgressReport,
    egress_identifiers,
    gate_egress,
    residue_message,
    scan_egress,
)
from engine.contracts import ContractError
from engine.kb import KBStore
from engine.llm import effective_config
from engine.runlog import RunLogger, read_run
from engine.version import engine_version
from engine.workspace import PursuitDir

OTHER = "Zephyrline Logistics"          # another client, indexed
BUYER = "Northwind Regional Health"     # this pursuit's buyer
FIRM = "Synthetic Advisory LLP"
PROV = {"source_pursuit": "pur_other", "source_client": OTHER,
        "date": "2025-02-02", "ingested_by": "ingestion_agent"}


def _workspace(tmp_path):
    store = KBStore(tmp_path / "kb")
    store.write_card(
        {"kb_id": "kb_other000001", "layer": "corpus",
         "summary": "A section from [CLIENT]."},
        "Body from [CLIENT].", PROV,
        {OTHER: "CLIENT", "ops@zephyrline.example": "CONTACT"})
    (tmp_path / "firm.json").write_text(json.dumps({"name": FIRM}),
                                        encoding="utf-8")
    pursuit = PursuitDir(tmp_path, "pur_egress")
    (pursuit.root / "brief.json").write_text(
        json.dumps({"buyer": {"name": BUYER}}), encoding="utf-8")
    return store, pursuit


def test_the_universe_is_the_index_minus_this_buyer_and_the_firm(tmp_path):
    store, pursuit = _workspace(tmp_path)
    universe = egress_identifiers(tmp_path, pursuit, store)
    assert OTHER in universe
    assert "ops@zephyrline.example" in universe
    assert BUYER not in universe and FIRM not in universe
    # the index read is logged under the engine's own grant, not silent
    access = (tmp_path / "kb" / "restricted" / "access.jsonl")
    lines = [json.loads(l) for l in access.read_text().splitlines()]
    assert any(l["actor"] == "engine" and l["action"] == "scan_index"
               and l["granted"] for l in lines)


def test_an_indexed_identifier_blocks_and_the_report_never_names_it():
    texts = {"sec-01:answer:0": f"We did this before for {OTHER}, twice.",
             "sec-02:prose": "Nothing to see here."}
    report = scan_egress("submission_render", texts, {OTHER})
    assert not report.passed
    assert [r["location"] for r in report.blocking] == ["sec-01:answer:0"]
    row = report.blocking[0]
    assert row["class"].startswith("kb_identifier:sha256:")
    assert row["count"] == 1 and row["id"].startswith("eg_")
    serialised = json.dumps(report.to_dict()) + residue_message(report)
    for word in ("Zephyrline", "Logistics", OTHER):
        assert word not in serialised


def test_a_structured_class_is_counted_but_does_not_block():
    texts = {"sec-03:prose": "Reach us at hello@firm.example or 555-123-4567."}
    report = scan_egress("submission_render", texts, set())
    assert report.passed
    classes = {r["class"] for r in report.rows}
    assert classes == {"<contact_info>"}
    assert report.rows[0]["count"] == 2  # two distinct contact values
    assert "hello@firm.example" not in json.dumps(report.to_dict())


def test_the_row_id_is_stable_across_runs():
    texts = {"sec-01:answer:0": f"{OTHER} again."}
    a = scan_egress("submission_render", texts, {OTHER})
    b = scan_egress("submission_render", texts, {OTHER})
    assert a.rows[0]["id"] == b.rows[0]["id"]
    c = scan_egress("xlsx_writeback", texts, {OTHER})
    assert c.rows[0]["id"] != a.rows[0]["id"]  # the lane is part of it


def test_gate_egress_records_the_line_and_refuses_typed(tmp_path):
    store, pursuit = _workspace(tmp_path)
    log = RunLogger(pursuit.root, pursuit.new_run_id(), pursuit.pursuit_id)
    cfg = effective_config()
    log.run_start(mode="dry_run", engine_version=engine_version(), config=cfg,
                  kb_snapshot=store.snapshot(),
                  research_mode=cfg["research_mode"])
    universe = egress_identifiers(tmp_path, pursuit, store)
    clean = gate_egress("submission_render",
                        {"t": f"A proposal for {BUYER} by {FIRM}."},
                        universe, log, agent="exporter")
    assert clean.passed
    with pytest.raises(ContractError) as exc:
        gate_egress("submission_render", {"sec-01:prose": f"As at {OTHER}."},
                    universe, log, agent="exporter")
    assert "identifier residue at 1 location(s)" in str(exc.value)
    assert "sec-01:prose" in str(exc.value) and OTHER not in str(exc.value)
    log.run_end(status="failed")
    records = read_run(log.path)
    lines = [r["validation"] for r in records
             if r.get("record_type") == "validation"]
    assert lines == [{"check": CHECK, "result": "pass"},
                     {"check": CHECK, "result": "block"}]


def test_the_report_shape_is_value_free_by_construction():
    report = EgressReport(lane="submission_render")
    assert report.passed and report.to_dict()["rows"] == []
    assert set(report.to_dict()) == {"check", "lane", "passed", "rows"}


def test_the_render_scans_every_string_it_writes(tmp_path, monkeypatch):
    """Structural (the ingest scan-set pin applied at the exit): the
    render scans ONE set and writes exactly that set — every non-empty
    paragraph of the produced docx is a string the gate saw, keyed by a
    location label a refusal can name."""
    import engine.assembly.docx as docx_mod
    from docx import Document
    from engine.assembly.docx import SUBMISSION_NAME, render_submission
    from tests.assembly.test_docx_writeback import _log
    from tests.validation.fixtures.validations import run_validation_package

    pursuit, report, _ = run_validation_package(tmp_path)
    assert report.status == "complete"
    seen: dict[str, str] = {}
    real = docx_mod.gate_egress

    def spy(lane, texts, identifiers, log, **kw):
        seen.update(texts)
        return real(lane, texts, identifiers, log, **kw)
    monkeypatch.setattr(docx_mod, "gate_egress", spy)
    log = _log(pursuit)
    render_submission(pursuit, log, at="2026-08-29T12:00:00Z")
    log.run_end(status="completed")
    written = [p.text for p in Document(str(pursuit.root / SUBMISSION_NAME))
               .paragraphs if p.text.strip()]
    assert written and set(written) <= set(seen.values())
    assert "title" in seen and any(k.endswith(":answer:0") for k in seen)
