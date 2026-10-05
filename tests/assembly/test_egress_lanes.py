"""The egress gate at the three write-back lanes (P32a, A6's pre-export
scan): each lane scans exactly the strings it is about to write, refuses
typed before any output exists, names locations and counts (never the
text), and records the `pre_export_leakage` line; the template fill
scans the buyer-copy path (prose + hand-typed values) and leaves the
internal working copy unscanned; a pricing grid restating nothing the
index holds is not residue."""

import pytest

from engine.assembly.docx_writeback import run_docx_writeback
from engine.assembly.egress import EgressResidue
from engine.assembly.template_fill import (
    OUTPUT_NAME,
    WORKING_NAME,
    run_template_fill,
)
from engine.assembly.writeback import run_writeback
from engine.kb import KBStore
from engine.runlog import read_run
from tests.assembly.test_docx_writeback import AT as DOCX_AT
from tests.assembly.test_docx_writeback import _log
from tests.assembly.test_docx_writeback import _workspace as docx_workspace
from tests.assembly.test_template_fill import AT as FILL_AT
from tests.assembly.test_template_fill import FULL_HAND
from tests.assembly.test_template_fill import _workspace as fill_workspace
from tests.assembly.test_xlsx_patch_roundtrip import AT as XLSX_AT
from tests.assembly.test_xlsx_patch_roundtrip import _pursuit as xlsx_pursuit

OTHER_PROV = {"source_pursuit": "pur_other", "source_client":
              "Zephyrline Logistics", "date": "2025-02-02",
              "ingested_by": "ingestion_agent"}


def _index(workspace, **identifiers) -> None:
    """Another client's card in the workspace's own store — its
    identifiers enter the restricted index the lanes scan against."""
    KBStore(workspace / "kb").write_card(
        {"kb_id": "kb_other000001", "layer": "corpus",
         "summary": "A section from [CLIENT]."},
        "Body from [CLIENT].", OTHER_PROV, dict(identifiers))


def _lines(log) -> list[dict]:
    return [r["validation"] for r in read_run(log.path)
            if r.get("record_type") == "validation"]


def test_the_xlsx_lane_refuses_before_any_output_exists(tmp_path):
    pursuit = xlsx_pursuit(tmp_path)
    _index(tmp_path / "ws", **{"employee-owned": "CLIENT"})
    log = _log(pursuit)
    with pytest.raises(EgressResidue) as exc:
        run_writeback(pursuit, log, at=XLSX_AT, confirmed_by="Pat Lead")
    message = str(exc.value)
    assert "xlsx_writeback: identifier residue at 1 location(s)" in message
    assert "1. Questions!C2 (1)" in message and "employee" not in message
    exports = pursuit.root / "exports"
    assert not exports.exists() or not list(exports.rglob("*.xlsx"))
    assert {"check": "pre_export_leakage", "result": "block"} in _lines(log)


def test_the_docx_lane_passes_clean_and_refuses_over_the_index(tmp_path):
    pursuit = docx_workspace(tmp_path, "qform-twin.docx")
    log = _log(pursuit)
    facts = run_docx_writeback(pursuit, log, at=DOCX_AT,
                               confirmed_by="Pat Lead")
    output = pursuit.root / facts["output_file"]
    assert output.is_file()
    assert _lines(log) == [{"check": "pre_export_leakage", "result": "pass"}]
    _index(tmp_path, **{"employee-owned": "CLIENT"})
    with pytest.raises(EgressResidue) as exc:
        run_docx_writeback(pursuit, log, at=DOCX_AT, confirmed_by="Pat Lead")
    message = str(exc.value)
    assert "docx_writeback: identifier residue" in message
    assert "table0:row1:col1 (1)" in message and "employee" not in message
    # P2-56 at this door: the earlier pass's file never outlives the refusal
    assert not output.exists()
    assert _lines(log)[-1] == {"check": "pre_export_leakage",
                               "result": "block"}


def test_the_template_fill_scans_the_buyer_copys_prose_and_hand_values(
        tmp_path):
    pursuit = fill_workspace(tmp_path, all_prose=True, hand=FULL_HAND)
    _index(tmp_path, Payroll="CLIENT")  # a value typed into the case block
    log = _log(pursuit)
    with pytest.raises(EgressResidue) as exc:
        run_template_fill(pursuit, log, confirmed_by="Pat", at=FILL_AT)
    message = str(exc.value)
    assert "template_fill: identifier residue at 1 location(s)" in message
    assert "hand:s-h10:1:scope (1)" in message and "Payroll" not in message
    assert not (pursuit.root / OUTPUT_NAME).exists()
    assert {"check": "pre_export_leakage", "result": "block"} in _lines(log)


def test_a_pricing_grid_restating_nothing_indexed_is_not_residue(tmp_path):
    """The false-positive class that trains operators to ignore the
    finding: a fee the index holds for another client, restated in
    every form the scanner derives, must not match fees that are not
    its restatements — nor a name that is simply not in the text."""
    pursuit = fill_workspace(tmp_path, all_prose=True, hand=FULL_HAND)
    _index(tmp_path, **{"$1,975,000": "REDACTED",
                        "Cascade Valley Medical Center": "CLIENT"})
    log = _log(pursuit)
    out = run_template_fill(pursuit, log, confirmed_by="Pat", at=FILL_AT)
    assert out["buyer_copy_produced"] is True
    assert (pursuit.root / OUTPUT_NAME).is_file()
    assert _lines(log) == [{"check": "pre_export_leakage", "result": "pass"}]


def test_a_working_copy_only_fill_is_internal_and_unscanned(tmp_path):
    pursuit = fill_workspace(tmp_path)  # sections still owed: no buyer copy
    _index(tmp_path, **{"First paragraph": "CLIENT"})
    log = _log(pursuit)
    out = run_template_fill(pursuit, log, confirmed_by="Pat", at=FILL_AT,
                            store=KBStore(tmp_path / "kb"))
    assert out["buyer_copy_produced"] is False
    assert (pursuit.root / WORKING_NAME).is_file()
    assert _lines(log) == []
