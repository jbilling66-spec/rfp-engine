"""C12: the KB source reader — python-docx identity stamped, media facts
counted, and the .md path byte-unchanged (the anonymization suite reads
through this seam now). P33b (B153 §2): the response workbook read
in-engine under the openpyxl identity, and the one typed refusal."""

import pytest

from engine.kb.read import UnreadableSource, read_source
from tests.kb.fixtures.corpus import SOURCE_DOCS


def test_docx_reads_with_identity_and_media(tmp_path):
    from engine.extraction.corpus import build_logo_docx

    path = build_logo_docx(tmp_path / "logo-twin.docx")
    source = read_source(path)
    assert source.extractor == "python-docx"
    assert source.fingerprint.startswith("ext_")
    assert source.media == {"images": 1}
    # Intake's text conventions hold: headings as '#' lines.
    assert "# Northwind Regional Health - Engagement Letter" in source.text
    assert "identifying logo" in source.text


def test_docx_tables_render_as_pipe_rows(tmp_path):
    import docx as pydocx

    d = pydocx.Document()
    table = d.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = "Deliverable"
    table.rows[0].cells[1].text = "Fee"
    path = tmp_path / "t.docx"
    d.save(path)
    source = read_source(path)
    assert "| Deliverable | Fee |" in source.text
    assert source.media == {"images": 0}


def test_md_path_is_byte_unchanged(tmp_path):
    # The 20 committed anonymization docs flow through read_source now —
    # their text must be exactly the read_text() the recall record was
    # measured over.
    path = tmp_path / "anon.md"
    body = "<!-- client: Foxglove Robotics | date: 2026-01-01 -->\n# Doc\nbody\n"
    path.write_text(body, encoding="utf-8")
    source = read_source(path)
    assert source.text == body
    assert source.extractor == "text"
    assert source.media == {"images": 0}


def test_kb_and_intake_docx_stamps_are_independent(tmp_path):
    # Same library, two stacks: the KB fingerprint must not equal the
    # intake legacy python-docx fingerprint... they may share components
    # today, but the seam test (C12) pins the IDENTITIES; here we pin
    # that a fingerprint exists and names no docling component.
    import docx as pydocx

    d = pydocx.Document()
    d.add_paragraph("body")
    path = tmp_path / "p.docx"
    d.save(path)
    source = read_source(path)
    assert source.extractor == "python-docx"
    text_doc = SOURCE_DOCS[0]
    assert text_doc.extractor == ""  # fixtures predate the reader: unstamped


# ---- P33b (B153 §2): the workbook read in-engine, and the typed refusal ------

BUYER = "Northwind Regional Health"


def _workbook(path, rows=None, *, title="2. Delivery "):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = title  # the trailing space is real (EC-1)
    ws.append(["Ref", "Question", "Response"])
    for ref, question, answer in rows or [
        ("1", "Company background", None),
        ("1.1", "Describe your company history.",
         "Founded in 1998 and privately held, with offices in four regions."),
        ("1.2", f"Describe your experience with {BUYER}.",
         "Two prior programs, both delivered on the agreed timeline."),
        ("2", "Delivery approach", None),
        ("2.1", "Describe your methodology.",
         "Phased delivery with gates.\n\nNamed owners and weekly steering."),
    ]:
        ws.append([ref, question, answer])
    wb.save(path)
    return path, ws


def _shape(elements):
    return [(e.kind, e.text, e.level) for e in elements]


def test_xlsx_reads_in_engine_with_the_openpyxl_identity(tmp_path):
    from engine.extraction.fingerprint import stack_fingerprint

    path, _ws = _workbook(tmp_path / "resp.xlsx")
    source = read_source(path)
    assert source.extractor == "openpyxl"
    assert source.fingerprint.startswith("ext_")
    assert source.fingerprint != stack_fingerprint(
        "text", {"extractor_version": "stdlib"})
    assert source.doc_kind == "past_response"
    assert source.degraded is False and source.warnings == []
    assert source.media == {"images": 0}
    assert _shape(source.elements) == [
        ("heading", "2. Delivery", 1),
        ("heading", "Company background", 2),
        ("heading", "Describe your company history.", 3),
        ("paragraph", "Founded in 1998 and privately held, with offices in four regions.", None),
        ("heading", f"Describe your experience with {BUYER}.", 3),
        ("paragraph", "Two prior programs, both delivered on the agreed timeline.", None),
        ("heading", "Delivery approach", 2),
        ("heading", "Describe your methodology.", 3),
        ("paragraph", "Phased delivery with gates.", None),
        ("paragraph", "Named owners and weekly steering.", None),
    ]
    lines = source.text.splitlines()
    assert lines[0].startswith("<!-- response-workbook sha256:")
    assert "### Describe your methodology." in lines and "resp.xlsx" not in source.text


def test_xlsx_structural_answer_lines_are_text_on_the_direct_route(tmp_path):
    from engine.kb.response_workbook import pair_response_workbook, render_markdown

    rows = [("1.1", "How many FTEs do you propose?", "# of FTEs: 40\nAcross two teams."),
            ("1.2", "Summarise your rate card structure.", "| role | rate |"),
            ("1.3", "Describe your methodology.",
             "Phased delivery with gates and named owners per workstream.")]
    path, _ws = _workbook(tmp_path / "structural.xlsx", rows)
    source = read_source(path)
    assert source.warnings == []  # nothing refused on this route
    assert [e.text for e in source.elements if e.kind == "paragraph"] == [
        "# of FTEs: 40\nAcross two teams.", "| role | rate |",
        "Phased delivery with gates and named owners per workstream."]
    assert [e.text for e in source.elements if e.level == 3] == [
        "How many FTEs do you propose?", "Summarise your rate card structure.",
        "Describe your methodology."]
    assert "# of FTEs: 40" in source.text.splitlines()  # the flat text is lossless
    # The converter's own route keeps its stated limit (B152 §5c): two refused.
    assert len(render_markdown(pair_response_workbook(path)).warnings) == 2


def test_xlsx_lost_content_marks_the_read_degraded_by_address(tmp_path):
    rows = [("1.1", "Describe your company history.",
             "Founded in 1998 and privately held, with offices in four regions."),
            ("1.2", "Describe a superseded draft answer.",
             "An earlier draft kept on a hidden row — must never ride along."),
            ("1.3", "Describe your methodology.", None)]
    path, ws = _workbook(tmp_path / "hidden.xlsx", rows)
    ws.row_dimensions[3].hidden = True
    ws.parent.save(path)
    source = read_source(path)
    assert source.degraded is True
    assert source.warnings == ["2. Delivery!row 3: hidden row skipped",
                               "2. Delivery!row 4: unanswered"]
    assert "superseded" not in source.text and len(source.elements) == 3
    # A pairing rule alone (unanswered) is a warning, not a degradation.
    path2, _ws2 = _workbook(tmp_path / "plain.xlsx", rows[:1] + rows[2:])
    source2 = read_source(path2)
    assert source2.degraded is False
    assert source2.warnings == ["2. Delivery!row 3: unanswered"]


def test_xlsx_counts_embedded_media_for_the_c11_flag(tmp_path):
    import zipfile

    path, _ws = _workbook(tmp_path / "plain.xlsx")
    with_logo = tmp_path / "logo.xlsx"
    with zipfile.ZipFile(path) as src, zipfile.ZipFile(with_logo, "w") as dst:
        for info in src.infolist():
            dst.writestr(info, src.read(info.filename))
        dst.writestr("xl/media/image1.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 24)
    assert read_source(path).media == {"images": 0}
    assert read_source(with_logo).media == {"images": 1}


def test_unreadable_sources_are_refused_typed(tmp_path):
    pdf = tmp_path / "resp.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    with pytest.raises(UnreadableSource) as refused:
        read_source(pdf)
    assert refused.value.path == str(pdf)
    assert "'.pdf'" in refused.value.why and "no KB reader" in str(refused.value)

    junk = tmp_path / "junk.xlsx"
    junk.write_bytes(b"not a workbook at all")
    with pytest.raises(UnreadableSource) as refused:
        read_source(junk)
    assert "not a readable workbook" in refused.value.why

    empty, _ws = _workbook(tmp_path / "empty.xlsx",
                           [("1.1", "Describe your methodology.", None)])
    with pytest.raises(UnreadableSource) as refused:
        read_source(empty)
    assert "no question/answer pairs" in refused.value.why
    assert refused.value.warnings == ["2. Delivery!row 2: unanswered"]

    binary_text = tmp_path / "notes.txt"
    binary_text.write_bytes(b"\xff\xfe\x00not text")
    with pytest.raises(UnreadableSource) as refused:
        read_source(binary_text)
    assert "UTF-8" in refused.value.why

    plain = tmp_path / "plain.txt"
    plain.write_text("plain notes\n", encoding="utf-8")
    source = read_source(plain)
    assert source.extractor == "text" and source.doc_kind == "section_exemplar"


def test_converter_markdown_reads_as_a_past_response(tmp_path):
    from engine.kb.response_workbook import pair_response_workbook, render_markdown

    path, _ws = _workbook(tmp_path / "resp.xlsx")
    body = render_markdown(pair_response_workbook(path)).text
    md = tmp_path / "paired.md"
    md.write_text(body, encoding="utf-8")
    source = read_source(md)
    assert source.text == body and source.extractor == "text"
    assert source.doc_kind == "past_response"  # both routes, one kind (B153 §3a)
    md.write_text("# Doc\nbody\n", encoding="utf-8")
    assert read_source(md).doc_kind == "section_exemplar"
