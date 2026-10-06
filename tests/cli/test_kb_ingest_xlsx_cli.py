"""P33b (B153 §2): the production ingest door reads a completed response
workbook directly — offline here, through the two scripted readers — mints
one `past_response` card per answered question, prints the pairing's
warnings by address, and refuses an unreadable source typed, minting
nothing. Expectations are hand-derived from the in-test workbooks.
"""

import json

from openpyxl import Workbook

from engine.cli.main import main
from engine.kb import KBStore

BUYER = "Northwind Regional Health"
WIRE = json.dumps({"chunk_annotations": [], "qa_pairs": [], "identifiers": [],
                   "client_descriptor": "a regional health system"})
REVIEW = json.dumps({"identifiers": []})
ROWS = [
    ("1", "Company background", None),
    ("1.1", "Describe your company history.",
     "Founded in 1998 and privately held, with offices in four regions."),
    ("1.2", f"Describe your experience with {BUYER}.",
     "Two prior programs, both delivered on the agreed timeline."),
    ("1.3", "How many FTEs do you propose?", "# of FTEs: 40\nAcross two teams."),
    ("1.4", "Describe a superseded draft answer.",
     "An earlier draft kept on a hidden row that must never ride along."),
    ("1.5", "Describe your methodology.", None),
]


def _workbook(path, rows=ROWS, *, hidden_row=None):
    wb = Workbook()
    ws = wb.active
    ws.title = "2. Delivery"
    ws.append(["Ref", "Question", "Response"])
    for row in rows:
        ws.append(list(row))
    if hidden_row is not None:
        ws.row_dimensions[hidden_row].hidden = True
    wb.save(path)
    return path


def _args(tmp_path, file, *extra):
    wire, review = tmp_path / "wire.json", tmp_path / "review.json"
    wire.write_text(WIRE, encoding="utf-8")
    review.write_text(REVIEW, encoding="utf-8")
    return ["kb", "ingest", "--kb", str(tmp_path / "kb"), "--file", str(file),
            "--client", BUYER, "--pursuit", "pur_wb", "--date", "2026-01-01",
            "--wire", str(wire), "--reviewer-wire", str(review), *extra]


def test_kb_ingest_reads_a_workbook_directly(tmp_path, capsys):
    xlsx = _workbook(tmp_path / "resp.xlsx", hidden_row=6)  # row 6 = ref 1.4
    assert main(_args(tmp_path, xlsx)) == 0
    captured = capsys.readouterr()
    assert ": ingested, +3 cards" in captured.out
    assert captured.err.splitlines() == [
        "warning: 2. Delivery!row 6: hidden row skipped",
        "warning: 2. Delivery!row 7: unanswered",
    ]
    store = KBStore(tmp_path / "kb")
    cards = {c["title"]: c for c in store.list_cards()}
    assert sorted(cards) == [
        "Describe your company history.",
        "Describe your experience with [CLIENT].",  # the buyer, placeholdered
        "How many FTEs do you propose?",
    ]
    assert {c["doc_kind"] for c in cards.values()} == {"past_response"}
    # hidden content was LOST -> degraded, still ingested (B153 §3e)
    assert {c["extraction_status"] for c in cards.values()} == {"degraded"}
    _front, body = store.read_card(cards["How many FTEs do you propose?"]["kb_id"])
    assert body.strip() == "# of FTEs: 40\nAcross two teams."  # text, not structure
    everything = "\n".join(p.read_text(encoding="utf-8")
                           for p in (tmp_path / "kb" / "cards").glob("*.md"))
    assert "superseded" not in everything and BUYER not in everything


def test_kb_ingest_clean_workbook_is_not_degraded(tmp_path):
    xlsx = _workbook(tmp_path / "clean.xlsx", ROWS[:3])
    assert main(_args(tmp_path, xlsx)) == 0
    cards = KBStore(tmp_path / "kb").list_cards()
    assert len(cards) == 2
    assert {c["extraction_status"] for c in cards} == {"clean"}


def test_kb_ingest_refuses_unreadable_sources_typed_and_mints_nothing(tmp_path, capsys):
    pdf = tmp_path / "resp.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    assert main(_args(tmp_path, pdf)) == 1
    err = capsys.readouterr().err
    assert err.startswith("ingest refused: ") and "'.pdf'" in err
    assert "Traceback" not in err
    assert not (tmp_path / "kb" / "runs").exists()
    assert not list((tmp_path / "kb").glob("cards/*.md"))

    empty = _workbook(tmp_path / "empty.xlsx", [("1.1", "Describe your methodology.", None)])
    assert main(_args(tmp_path, empty)) == 1
    err = capsys.readouterr().err
    assert "no question/answer pairs" in err
    assert "  warning: 2. Delivery!row 2: unanswered" in err.splitlines()
    assert not (tmp_path / "kb" / "runs").exists()


def test_kb_ingest_of_the_converter_markdown_mints_the_same_kind(tmp_path, capsys):
    xlsx = _workbook(tmp_path / "resp.xlsx", ROWS[:3])
    md = tmp_path / "resp.md"
    assert main(["kb", "pair", "--file", str(xlsx), "--out", str(md)]) == 0
    assert main(_args(tmp_path, md)) == 0
    cards = KBStore(tmp_path / "kb").list_cards()
    assert len(cards) == 2 and {c["doc_kind"] for c in cards} == {"past_response"}
    plain = tmp_path / "plain.md"
    plain.write_text("# Doc\n\n## Data Migration\n\nRehearsed twice before cutover.\n",
                     encoding="utf-8")
    assert main(_args(tmp_path, plain)) == 0
    kinds = {c["doc_kind"] for c in KBStore(tmp_path / "kb").list_cards()}
    assert kinds == {"past_response", "section_exemplar"}
