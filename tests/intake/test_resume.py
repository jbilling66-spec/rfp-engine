"""Resume (N2): a run killed after the intake checkpoint resumes to a
byte-identical brief."""

import pytest

from tests.intake.fixtures.packages import run_package


class Boom(Exception):
    pass


def test_resume_after_intake_checkpoint_is_byte_identical(tmp_path):
    reference, _ = run_package(tmp_path / "ref", "pdf")
    reference_bytes = (reference.root / "brief.json").read_bytes()

    def exploding(prompt: str) -> str:
        raise Boom("killed between intake checkpoint and model call")

    crash_root = tmp_path / "crash"
    with pytest.raises(Boom):
        run_package(crash_root, "pdf", script={"intake_analyst": exploding})
    crashed = crash_root / "pur_pdf"
    assert (crashed / "checkpoints" / "intake.json").exists()
    assert not (crashed / "brief.json").exists()

    resumed, report = run_package(crash_root, "pdf")
    assert report.status == "complete"
    assert (resumed.root / "brief.json").read_bytes() == reference_bytes
