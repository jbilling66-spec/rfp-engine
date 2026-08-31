"""C10 — zero silent fabrication in the production path: table-bearing
docling PDFs get the two-path diff at intake; divergence and an unrunnable
VLM leg both force review; agreement stays clean; DOCX and resume never
re-run the second read."""

import json

from engine.extraction.backend import ExtractionFailed
from tests.extraction.fakes import FakeExtractionBackend, simple_view
from tests.intake.test_brief_backend import _pdf_twin_view
from tests.intake.fixtures.packages import run_package

GRID = [["Criterion", "Weight"], ["Technical approach", "40%"]]
DIVERGED = [["Criterion", "Weight"], ["Technical approach", "45%"]]


def _views(vlm_grid=None, vlm_exc=None):
    det = _pdf_twin_view() | {"grids": [{"grid": GRID, "merges": []}]}
    views = {"pdf-twin.pdf": det}
    if vlm_exc is not None:
        views["pdf-twin.pdf:vlm"] = vlm_exc
    else:
        views["pdf-twin.pdf:vlm"] = simple_view(
            "vlm", pages=det["pages"],
            grids=[{"grid": vlm_grid if vlm_grid is not None else GRID,
                    "merges": []}],
        )
    return views


def _artifact(pursuit):
    return json.loads((pursuit.root / "extraction.json").read_text())


def test_agreement_is_clean_and_recorded(tmp_path):
    fake = FakeExtractionBackend(_views())
    pursuit, report = run_package(tmp_path, "pdf", extraction=fake)
    assert report.status == "complete"
    art = _artifact(pursuit)
    assert art["two_path"]["pdf-twin.pdf"] == {"tables_diffed": 1, "findings": []}
    assert art["docs"][0]["mandatory_review"] is False
    assert fake.calls == [("pdf-twin.pdf", "deterministic"),
                          ("pdf-twin.pdf", "vlm")]


def test_divergence_forces_review_and_flags_run_log(tmp_path):
    fake = FakeExtractionBackend(_views(vlm_grid=DIVERGED))
    pursuit, report = run_package(tmp_path, "pdf", extraction=fake)
    assert report.status == "complete"  # recorded for review, never a refusal
    art = _artifact(pursuit)
    doc = art["docs"][0]
    assert doc["flags"] == ["two_path_divergence"]
    assert doc["mandatory_review"] is True
    findings = art["two_path"]["pdf-twin.pdf"]["findings"]
    assert findings == [{"table": 0, "row": 1, "col": 1,
                         "kind": "value_differs", "a": "40%", "b": "45%"}]
    run_dir = next((pursuit.root / "runs").iterdir())
    records = [json.loads(line) for line in
               (run_dir / "run.jsonl").read_text().splitlines()]
    assert {"check": "extraction", "result": "flag"} in [
        r["validation"] for r in records if r["record_type"] == "validation"
    ]


def test_vlm_leg_failure_flags_unavailable(tmp_path):
    fake = FakeExtractionBackend(
        _views(vlm_exc=ExtractionFailed("vlm conversion failure"))
    )
    pursuit, _ = run_package(tmp_path, "pdf", extraction=fake)
    art = _artifact(pursuit)
    assert art["docs"][0]["flags"] == ["two_path_unavailable"]
    assert art["docs"][0]["mandatory_review"] is True
    assert "vlm path failed" in art["two_path"]["pdf-twin.pdf"]["error"]


def test_tableless_pdf_skips_the_second_read(tmp_path):
    fake = FakeExtractionBackend({"pdf-twin.pdf": _pdf_twin_view()})
    pursuit, _ = run_package(tmp_path, "pdf", extraction=fake)
    assert _artifact(pursuit)["two_path"] == {}
    assert fake.calls == [("pdf-twin.pdf", "deterministic")]


def test_resume_never_rediffs(tmp_path):
    class Boom(Exception):
        pass

    def exploding(prompt: str) -> str:
        raise Boom("killed post-checkpoint")

    fake = FakeExtractionBackend(_views())
    crash_root = tmp_path / "crash"
    try:
        run_package(crash_root, "pdf", extraction=fake,
                    script={"intake_analyst": exploding})
    except Boom:
        pass
    calls_after_crash = list(fake.calls)
    run_package(crash_root, "pdf", extraction=fake)
    # The deterministic read reruns on resume (doc text feeds the model
    # call), but the VLM leg is checkpoint-guarded: no re-diff.
    assert fake.calls == calls_after_crash + [("pdf-twin.pdf", "deterministic")]
