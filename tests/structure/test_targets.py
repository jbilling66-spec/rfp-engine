"""The declared-target surface (P16/C4): dispatch, the core-document
scan (B67-F3 — THE named test that slots inside the narrative RFP are
captured), and the one-or-many container merge whose single-file shape
is byte-pinned pre-P16.
"""

from pathlib import Path

import pytest

from engine.contracts import validate
from engine.structure import (
    StructureError,
    merge_parsed,
    parse_target,
    parse_workbook,
    scan_core_document,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_dispatch_xlsx_is_the_pinned_parser():
    via_target = parse_target(FIXTURES / "structured-twin.xlsx")
    direct = parse_workbook(FIXTURES / "structured-twin.xlsx")
    assert via_target.slots == direct.slots
    assert via_target.parser_version == direct.parser_version


def test_dispatch_docx_is_the_buyer_parser():
    parsed = parse_target(FIXTURES / "outline-twin.docx")
    assert parsed.source_mode == "client_provided"
    assert parsed.slot_count == 6


def test_unsupported_declared_target_refuses_loudly(tmp_path):
    stray = tmp_path / "target.pdf"
    stray.write_bytes(b"%PDF-1.4 not a real form")
    with pytest.raises(StructureError, match="never degrades to free_flow"):
        parse_target(stray)


def test_slots_inside_the_narrative_are_captured():
    """B67-F3, the acceptance row's named case: the narrative core
    carries a mandated outline AND a fill-in table (labels filled,
    answer columns empty) — both become slots; the fully-filled phase
    table becomes NOTHING."""
    parsed = scan_core_document(FIXTURES / "narrative-twin.docx")
    for slot in parsed.slots:
        validate("target_slot", slot)
    refs = [s.get("ref_id") for s in parsed.slots if s.get("ref_id")]
    assert refs == ["1", "2"]  # the embedded outline
    fillin = next(s for s in parsed.slots
                  if s.get("fill_type") == "template_fill")
    assert [f["label"] for f in fillin["response_fields"]] == [
        "Name", "% Allocation"]  # only the EMPTY columns are asks
    assert fillin["source_locator"]["docx_anchor"] == "Resource Commitments"
    assert "Role" in fillin["question_text"]  # the filled label column named
    assert not any("Phase" in (s.get("question_text") or "")
                   for s in parsed.slots)  # filled table = buyer content


def test_core_scan_finding_nothing_is_normal(tmp_path):
    from docx import Document
    doc = Document()
    doc.add_paragraph("Pure narrative with no response structure.")
    plain = tmp_path / "plain.docx"
    doc.save(plain)
    assert scan_core_document(plain).slots == []
    assert scan_core_document(FIXTURES / "pdf-twin.pdf") is None  # not docx


def test_single_target_merge_is_the_pre_p16_container_shape():
    parsed = parse_workbook(FIXTURES / "structured-twin.xlsx")
    body = merge_parsed([parsed])
    assert set(body) == {"source_mode", "parser_version", "source_sha256",
                         "slot_count", "slots"}  # no sources[] — the pin
    assert body["slots"] is parsed.slots
    assert body["source_sha256"] == parsed.source_sha256


def test_multi_target_merge_namespaces_and_carries_sources():
    xlsx = parse_workbook(FIXTURES / "demo-twin.xlsx")  # carries a gated pair
    docx = parse_target(FIXTURES / "qform-twin.docx")
    body = merge_parsed([docx, xlsx])
    assert body["slot_count"] == xlsx.slot_count + docx.slot_count
    assert body["source_sha256"] == docx.source_sha256  # first declared
    assert [s["file"] for s in body["sources"]] == [
        "qform-twin.docx", "demo-twin.xlsx"]
    validate("target_slots", {"pursuit_id": "pur_test", **body})

    assert all(s["slot_id"].startswith(("f00-", "f01-"))
               for s in body["slots"])
    child = next(s for s in body["slots"]
                 if s["slot_id"] == "f00-s-t00-r01")
    assert child["parent"] == "f00-s-r1"  # parent remapped with its file
    gater = next(s for s in body["slots"]
                 if s.get("gating", {}).get("gates"))
    assert all(g.startswith("f01-") for g in gater["gating"]["gates"])
