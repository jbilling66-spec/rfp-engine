"""C11: media_findings — identity classes flag above the floor, everything
else is furniture; the intake adapter carries the finding into flags."""

from engine.extraction.media import media_findings
from engine.intake.extract import extract
from tests.extraction.fakes import FakeExtractionBackend, simple_view


def test_logo_and_signature_flag():
    figures = [
        {"classes": [{"label": "logo", "confidence": 0.97}]},
        {"classes": [{"label": "signature", "confidence": 0.81}]},
    ]
    assert media_findings(figures) == ["figure_logo", "figure_signature"]


def test_ordinary_figures_are_furniture():
    figures = [
        {"classes": [{"label": "bar_chart", "confidence": 0.99}]},
        {"classes": [{"label": "map", "confidence": 0.95}]},
        {"classes": []},
    ]
    assert media_findings(figures) == []


def test_low_confidence_identity_does_not_flag():
    figures = [{"classes": [{"label": "logo", "confidence": 0.31}]}]
    assert media_findings(figures) == []


def test_duplicates_dedupe():
    figures = [
        {"classes": [{"label": "logo", "confidence": 0.9}]},
        {"classes": [{"label": "logo", "confidence": 0.8}]},
    ]
    assert media_findings(figures) == ["figure_logo"]


def test_adapter_carries_figure_flags_to_review(tmp_path):
    import docx as pydocx

    path = tmp_path / "letter.docx"
    d = pydocx.Document()
    d.add_paragraph("Engagement letter body text.")
    d.save(path)
    fake = FakeExtractionBackend({
        "letter.docx": simple_view(
            "body", figures=[{"classes": [{"label": "logo", "confidence": 0.9}]}]
        )
    })
    doc = extract(path, backend=fake)
    assert doc.extraction_flags == ["figure_logo"]
