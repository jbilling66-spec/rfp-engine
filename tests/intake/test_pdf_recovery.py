"""P2-26 (P26b-1, B112): pypdf's recovery messages reach the document's
warnings. The damaged twin is the committed PDF twin with its startxref
pointer moved — pypdf rebuilds the xref, reads both pages and logs
"incorrect startxref pointer" on its own logger, which nothing in this
engine captured before; a partially-recovered file looked clean."""

import logging
import re
from pathlib import Path

from engine.intake.extract import extract

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _damaged(tmp_path: Path) -> Path:
    raw = (FIXTURES / "pdf-twin.pdf").read_bytes()
    damaged = re.sub(rb"startxref\s+(\d+)", b"startxref\n999999", raw, count=1)
    assert damaged != raw
    path = tmp_path / "damaged.pdf"
    path.write_bytes(damaged)
    return path


def test_recovery_is_a_recorded_warning(tmp_path):
    doc = extract(_damaged(tmp_path))
    assert "NORTHWIND REGIONAL HEALTH" in doc.text  # recovered, not refused
    recovery = [w for w in doc.warnings if w.startswith("pdf recovery: ")]
    assert any("incorrect startxref pointer" in w for w in recovery)


def test_a_clean_pdf_records_no_recovery():
    doc = extract(FIXTURES / "pdf-twin.pdf")
    assert not [w for w in doc.warnings if w.startswith("pdf recovery: ")]


def test_the_handler_is_scoped_to_the_read(tmp_path):
    logger = logging.getLogger("pypdf")
    before = list(logger.handlers)
    extract(_damaged(tmp_path))
    assert logger.handlers == before  # attached for one read, then removed
