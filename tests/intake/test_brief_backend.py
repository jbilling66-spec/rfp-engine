"""C9: intake carries extractor identity into the checkpoint, stays
byte-identical across kill/resume with a backend wired, and the pdf-twin
package runs unchanged through the docling seam (FakeExtractionBackend —
the offline suite proves the wire, the container leg proves the library)."""

import pypdf

from tests.extraction.fakes import FakeExtractionBackend, simple_view
from tests.intake.fixtures.packages import FIXTURES, run_package


def _pdf_twin_view():
    # Per-page text lifted from the committed twin via pypdf so the fake
    # view feeds the scripted analyst the same frames the legacy path does.
    reader = pypdf.PdfReader(FIXTURES / "pdf-twin.pdf")
    pages = [(p.extract_text() or "") for p in reader.pages]
    return simple_view("md export", pages=len(pages), page_texts=pages)


def test_checkpoint_carries_extractor_identity(tmp_path):
    fake = FakeExtractionBackend({"pdf-twin.pdf": _pdf_twin_view()})
    pursuit, report = run_package(tmp_path, "pdf", extraction=fake)
    assert report.status == "complete"
    docs = pursuit.checkpoint_payload("intake")["docs"]
    assert docs[0]["extractor"] == "docling"
    assert docs[0]["extraction_fingerprint"].startswith("ext_")
    assert docs[0]["extraction_degraded"] is False
    assert docs[0]["extraction_flags"] == []
    assert fake.calls == [("pdf-twin.pdf", "deterministic")]


def test_no_backend_checkpoint_is_honest_legacy(tmp_path):
    pursuit, report = run_package(tmp_path, "pdf")
    docs = pursuit.checkpoint_payload("intake")["docs"]
    assert docs[0]["extractor"] == "pypdf"
    assert docs[0]["extraction_degraded"] is True
    assert docs[0]["extraction_flags"] == ["legacy_extractor"]


def test_kill_resume_byte_identical_with_backend(tmp_path):
    class Boom(Exception):
        pass

    def exploding(prompt: str) -> str:
        raise Boom("killed post-checkpoint")

    fake = FakeExtractionBackend({"pdf-twin.pdf": _pdf_twin_view()})
    reference, _ = run_package(tmp_path / "ref", "pdf", extraction=fake)
    ref_brief = (reference.root / "brief.json").read_bytes()
    ref_ckpt = (reference.root / "checkpoints" / "intake.json").read_bytes()

    crash_root = tmp_path / "crash"
    try:
        run_package(crash_root, "pdf", extraction=fake,
                    script={"intake_analyst": exploding})
    except Boom:
        pass
    resumed, report = run_package(crash_root, "pdf", extraction=fake)
    assert report.status == "complete"
    assert (resumed.root / "brief.json").read_bytes() == ref_brief
    assert (resumed.root / "checkpoints" / "intake.json").read_bytes() == ref_ckpt


def test_xlsx_package_never_touches_the_backend(tmp_path):
    fake = FakeExtractionBackend({})  # would fail any convert call
    pursuit, report = run_package(tmp_path, "xlsx", extraction=fake)
    assert report.status == "complete"
    assert fake.calls == []
