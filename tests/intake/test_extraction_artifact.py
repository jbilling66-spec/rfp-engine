"""C10: the pursuit-workspace extraction artifact — per-document identity,
degraded state, and the code-forced mandatory_review; byte-stable across
resume (it is written inside the checkpoint guard)."""

import json

from tests.extraction.fakes import FakeExtractionBackend, simple_view
from tests.intake.fixtures.packages import run_package
from tests.intake.test_brief_backend import _pdf_twin_view


def _artifact(pursuit):
    return json.loads((pursuit.root / "extraction.json").read_text())


def test_clean_docling_doc_needs_no_review(tmp_path):
    fake = FakeExtractionBackend({"pdf-twin.pdf": _pdf_twin_view()})
    pursuit, _ = run_package(tmp_path, "pdf", extraction=fake)
    doc = _artifact(pursuit)["docs"][0]
    assert doc == {
        "file": "pdf-twin.pdf",
        "extractor": "docling",
        "extraction_fingerprint": doc["extraction_fingerprint"],
        "degraded": False,
        "flags": [],
        "mandatory_review": False,
    }
    assert doc["extraction_fingerprint"].startswith("ext_")


def test_degraded_doc_is_code_forced_to_review(tmp_path):
    view = _pdf_twin_view() | {"status": "partial_success"}
    fake = FakeExtractionBackend({"pdf-twin.pdf": view})
    pursuit, report = run_package(tmp_path, "pdf", extraction=fake)
    assert report.status == "complete"  # degraded still ingests
    doc = _artifact(pursuit)["docs"][0]
    assert doc["degraded"] is True
    assert doc["flags"] == ["partial_extraction"]
    assert doc["mandatory_review"] is True


def test_legacy_fallback_doc_is_flagged_for_review(tmp_path):
    pursuit, _ = run_package(tmp_path, "pdf")  # no backend: legacy stamped
    doc = _artifact(pursuit)["docs"][0]
    assert doc["extractor"] == "pypdf"
    assert doc["mandatory_review"] is True


def test_artifact_is_byte_stable_across_resume(tmp_path):
    class Boom(Exception):
        pass

    def exploding(prompt: str) -> str:
        raise Boom("killed post-checkpoint")

    fake = FakeExtractionBackend({"pdf-twin.pdf": _pdf_twin_view()})
    crash_root = tmp_path / "crash"
    try:
        run_package(crash_root, "pdf", extraction=fake,
                    script={"intake_analyst": exploding})
    except Boom:
        pass
    first = (crash_root / "pur_pdf" / "extraction.json").read_bytes()
    resumed, _ = run_package(crash_root, "pdf", extraction=fake)
    assert (resumed.root / "extraction.json").read_bytes() == first
