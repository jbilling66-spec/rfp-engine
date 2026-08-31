"""Container-only corpus traits (C4, B51) — first of the roster.

build_scanned_pdf needs PIL, which ships with docling: this module runs
inside the gate container (make gate) and is deselected everywhere else
via tests/extraction/seam.py. The assertions themselves use pypdf — it
is only the BUILD step that needs the container.
"""

from __future__ import annotations

import json
from pathlib import Path

from engine.extraction.corpus import build_scanned_pdf

ROOT = Path(__file__).resolve().parents[2]
GROUND_TRUTH = json.loads(
    (ROOT / "evals" / "extraction-gate" / "ground_truth.json").read_text()
)


def test_scanned_twin_is_image_only_with_the_expected_pages(tmp_path):
    from pypdf import PdfReader

    path = build_scanned_pdf(tmp_path / "scanned-twin.pdf")
    reader = PdfReader(path)
    truth = GROUND_TRUTH["scanned-twin.pdf"]
    assert len(reader.pages) == truth["pages"]
    # No text layer: the content is pixels, which is the entire point —
    # only OCR (the gate, via docling) can read must_contain back out.
    assert all(not page.extract_text().strip() for page in reader.pages)


def test_scanned_twin_carries_no_real_world_tokens(tmp_path):
    from tests.tripwire.tokens import scan_tokens

    data = build_scanned_pdf(tmp_path / "scanned-twin.pdf").read_bytes().lower()
    for token in scan_tokens():
        assert token.lower().encode() not in data
