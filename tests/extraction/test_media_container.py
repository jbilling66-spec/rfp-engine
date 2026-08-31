"""C11 container leg: the figure plumbing against real docling — DOCX
conversion carries embedded pictures into the view, and media_findings
consumes their (empty) class lists gracefully.

EVIDENCE LIMIT, recorded (B58): the synthetic corpus CANNOT elicit a
classifier positive — probed 2026-08-23 in-container: docling's DOCX
pipeline attaches no classification annotations, and the generated
three-band PNGs are too featureless for the layout model to segment as
figure elements even via the IMAGE pipeline. So the classified-positive
path (figure_logo/figure_signature -> flags) is proven by venv tests over
scripted views (test_media.py), and its real-document check is the A1
buyer-corpus rerun — the same named closer as the reading-order
re-measure. This module pins what synthetic evidence CAN pin."""

from engine.extraction.backend import InContainerBackend
from engine.extraction.corpus import build_logo_docx, build_signature_docx
from engine.extraction.media import media_findings


def test_docx_pictures_reach_the_view(tmp_path):
    backend = InContainerBackend()
    for name, builder in (("logo-twin.docx", build_logo_docx),
                          ("signature-twin.docx", build_signature_docx)):
        view = backend.convert(builder(tmp_path / name))
        assert len(view.figures) == 1, f"{name}: picture lost in conversion"
        # No classification on the DOCX pipeline — consumed gracefully,
        # never crashed on.
        assert media_findings(view.figures) == []
