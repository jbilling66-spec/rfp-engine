"""P2-27 (P26b-1, B112): intake reads a docx's header, footer and text
boxes — marked, in a stable position (headers first, footers last, text
boxes after their anchor) — so the brief and the injection screen see
buyer instructions placed there."""

from pathlib import Path

from engine.intake.extract import extract
from engine.intake.screen import screen_text
from tests.fixtures.docx_twins import (
    FOOTER_TEXT, HEADER_DIRECTIVE, TEXT_BOX_DIRECTIVE,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_parts_are_marked_and_positioned():
    doc = extract(FIXTURES / "parts-twin.docx")
    lines = doc.text.split("\n")
    assert lines[0] == f"[header] {HEADER_DIRECTIVE}"
    assert lines[-1] == f"[footer] {FOOTER_TEXT}"
    anchor = lines.index("Answer each question in the table below.")
    assert lines[anchor + 1] == f"[text box] {TEXT_BOX_DIRECTIVE}"


def test_the_screen_sees_what_the_parts_say():
    # The screen reads the extracted text, so a directive in a text box
    # is screened exactly like one in the body; this pins that the words
    # REACH the screen's input (which patterns fire is the screen's own
    # contract, tested in test_screen.py).
    doc = extract(FIXTURES / "parts-twin.docx")
    assert TEXT_BOX_DIRECTIVE in doc.text and HEADER_DIRECTIVE in doc.text
    screen_text(doc.text, source="parts-twin.docx")  # no crash on marked lines


def test_a_plain_docx_gains_no_markers():
    doc = extract(FIXTURES / "qform-twin.docx")
    assert "[header]" not in doc.text and "[footer]" not in doc.text
    assert "[text box]" not in doc.text
