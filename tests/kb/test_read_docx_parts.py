"""P2-27 (P26b-1, B112): KB ingestion's docx reader carries headers,
footers and text boxes into the source text and its element stream."""

from pathlib import Path

from engine.kb.read import read_source
from tests.fixtures.docx_twins import (
    FOOTER_TEXT, HEADER_DIRECTIVE, TEXT_BOX_DIRECTIVE,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_parts_reach_the_source_text_and_elements():
    source = read_source(FIXTURES / "parts-twin.docx")
    lines = source.text.split("\n")
    assert lines[0] == f"[header] {HEADER_DIRECTIVE}"
    assert lines[-1] == f"[footer] {FOOTER_TEXT}"
    assert f"[text box] {TEXT_BOX_DIRECTIVE}" in lines
    texts = [e.text for e in source.elements if e.kind == "paragraph"]
    assert HEADER_DIRECTIVE in texts and FOOTER_TEXT in texts
    assert TEXT_BOX_DIRECTIVE in texts


def test_a_plain_docx_is_unchanged():
    source = read_source(FIXTURES / "qform-twin.docx")
    assert "[header]" not in source.text and "[text box]" not in source.text
