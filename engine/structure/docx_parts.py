"""Headers, footers and text boxes of a .docx — the parts a body-only walk
never sees (P2-27, P26b-1, B112).

Every reader in this engine walked `document.element.body` (or
python-docx's `iter_inner_content`, which is the same walk), so buyer
instructions placed in a header, a footer or a floating text box were
absent from the brief, the slots and the injection screen's input. These
two helpers are the single implementation the intake, KB and structure
readers share; each caller decides how to mark what it gets.
"""

from __future__ import annotations

_HEADER_FOOTER = (
    ("header", "header"), ("header", "first_page_header"),
    ("header", "even_page_header"),
    ("footer", "footer"), ("footer", "first_page_footer"),
    ("footer", "even_page_footer"),
)


def header_footer_text(document) -> list[tuple[str, str]]:
    """Every distinct non-empty paragraph or table row in every section's
    headers and footers, as (kind, text) with kind ∈ {header, footer}, in
    document order. A part linked to the previous section is that
    section's part and is not repeated."""
    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for section in document.sections:
        for kind, attr in _HEADER_FOOTER:
            part = getattr(section, attr)
            if part.is_linked_to_previous:
                continue
            texts = [p.text.strip() for p in part.paragraphs if p.text.strip()]
            for table in part.tables:
                for row in table.rows:
                    cells = [c.text.strip() for c in row.cells if c.text.strip()]
                    if cells:
                        texts.append(" | ".join(cells))
            for text in texts:
                if (kind, text) in seen:
                    continue
                seen.add((kind, text))
                out.append((kind, text))
    return out


def text_box_text(element) -> list[str]:
    """The paragraphs inside every text box anchored under `element` (a
    paragraph's or cell's oxml element) — both the VML (`w:pict`) and the
    DrawingML (`wps:txbx`) carriers wrap their content in
    `w:txbxContent`, so one query covers both."""
    out: list[str] = []
    for para in element.xpath(".//w:txbxContent//w:p"):
        text = "".join(t.text or "" for t in para.xpath(".//w:t")).strip()
        if text:
            out.append(text)
    return out
