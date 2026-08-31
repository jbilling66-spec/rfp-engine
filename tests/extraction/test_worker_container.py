"""C9 container leg: the production seam against the real library — real
conversion, determinism across converts, the sidecar on DOCX, and a
malformed PDF failing harmlessly THROUGH the production path (the ROADMAP
clause is about production, not just the gate). Runs only where docling is
installed (the gate image); deselected everywhere else via the seam roster."""

import pytest

from engine.extraction.backend import ExtractionFailed, InContainerBackend
from engine.extraction.corpus import (
    build_complex_table_docx,
    build_multicolumn_pdf,
    build_table_pdf,
    build_truncated_pdf,
)
from engine.extraction.fingerprint import extraction_fingerprint, manifest_digest


@pytest.fixture(scope="module")
def backend():
    return InContainerBackend()  # construction verifies the 57 weights


def test_table_pdf_converts_to_a_typed_view(backend, tmp_path):
    doc = build_table_pdf(tmp_path / "table-pdf-twin.pdf")
    view = backend.convert(doc)
    assert view.status == "success"
    assert view.pages >= 1
    assert view.grids and view.grids[0].grid
    assert view.docling_version  # runtime version, stamped by the worker
    # PDFs carry per-page text so intake keeps its [page N] markers.
    assert view.page_texts and len(view.page_texts) == view.pages


def test_convert_twice_is_byte_identical(backend, tmp_path):
    # Production artifacts must be resume-stable: no timing crosses the
    # boundary, so two converts of the same bytes are the same view.
    doc = build_table_pdf(tmp_path / "table-pdf-twin.pdf")
    assert backend.convert(doc).to_dict() == backend.convert(doc).to_dict()


def test_docx_sidecar_carried_into_production(backend, tmp_path):
    doc = build_complex_table_docx(tmp_path / "complex-tables-twin.docx")
    view = backend.convert(doc)
    # The B57 layer design: shading docling drops is recovered beside it.
    assert view.sidecar["fills"], "sidecar fills missing on the production path"
    assert view.page_texts is None  # docx has no page geometry


def test_truncated_pdf_fails_harmlessly_via_production_seam(backend, tmp_path):
    source = build_table_pdf(tmp_path / "src.pdf")
    doc = build_truncated_pdf(tmp_path / "truncated-twin.pdf", source)
    sentinel = tmp_path / "host-state.txt"
    sentinel.write_text("untouched")
    with pytest.raises(ExtractionFailed):
        backend.convert(doc)
    # The jail contained it: the host process and filesystem are intact.
    assert sentinel.read_text() == "untouched"


def test_vlm_leg_converts_for_the_two_path_diff(backend, tmp_path):
    # C10's production diff needs the VLM mode through the same seam the
    # gate proved; the view is consulted for the diff and discarded.
    doc = build_table_pdf(tmp_path / "table-pdf-twin.pdf")
    view = backend.convert(doc, mode="vlm")
    assert view.status in ("success", "partial_success")
    assert view.pages >= 1


def test_multicolumn_twin_flags_and_plain_pdf_does_not(backend, tmp_path):
    # C13 on the real library: the gutter-less two-column probe (the
    # gate's known weak case) is detected; the single-column table twin
    # is not.
    multi = backend.convert(build_multicolumn_pdf(tmp_path / "multicolumn-twin.pdf"))
    assert multi.multicolumn_pages == [1]
    plain = backend.convert(build_table_pdf(tmp_path / "table-pdf-twin.pdf"))
    assert plain.multicolumn_pages == []


def test_fingerprint_composes_from_a_real_view(backend, tmp_path):
    doc = build_table_pdf(tmp_path / "table-pdf-twin.pdf")
    view = backend.convert(doc)
    stamp = extraction_fingerprint(view.docling_version, manifest_digest())
    assert stamp.startswith("ext_") and len(stamp) == 20
