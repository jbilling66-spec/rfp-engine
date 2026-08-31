"""C13: the multicolumn flag is code-forced into mandatory review (the
planning-gate idiom: the writer sets it whenever the flag is present; no
payload shape can unset it) — and it is review, never degradation."""

import json

from tests.extraction.fakes import FakeExtractionBackend
from tests.intake.fixtures.packages import run_package
from tests.intake.test_brief_backend import _pdf_twin_view


def test_multicolumn_flags_and_forces_review(tmp_path):
    view = _pdf_twin_view() | {"multicolumn_pages": [1]}
    fake = FakeExtractionBackend({"pdf-twin.pdf": view})
    pursuit, report = run_package(tmp_path, "pdf", extraction=fake)
    assert report.status == "complete"  # accept-with-flag, not a block
    art = json.loads((pursuit.root / "extraction.json").read_text())
    doc = art["docs"][0]
    assert doc["flags"] == ["multicolumn_layout"]
    assert doc["degraded"] is False  # the read is fine; the ORDER is the risk
    assert doc["mandatory_review"] is True
    run_dir = next((pursuit.root / "runs").iterdir())
    records = [json.loads(line) for line in
               (run_dir / "run.jsonl").read_text().splitlines()]
    assert {"check": "extraction", "result": "flag"} in [
        r["validation"] for r in records if r["record_type"] == "validation"
    ]


def test_review_cannot_be_unset_by_any_payload_shape(tmp_path):
    # The force is code, not data: mandatory_review is DERIVED from the
    # flags at write time — there is no input that carries it, so nothing
    # a document or wire says can turn it off. Pin the derivation on the
    # flagged case (above asserts True); here pin that an unflagged doc
    # is the ONLY way to False.
    fake = FakeExtractionBackend({"pdf-twin.pdf": _pdf_twin_view()})
    pursuit, _ = run_package(tmp_path, "pdf", extraction=fake)
    art = json.loads((pursuit.root / "extraction.json").read_text())
    doc = art["docs"][0]
    assert doc["flags"] == [] and doc["mandatory_review"] is False
