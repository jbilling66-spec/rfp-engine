"""P34a (B155 §2, P3-26): the production ingest door says what it wrote,
merged, skipped and flagged — ids only, never text — and `--dry-run` says
the same in the conditional while writing nothing to the store but its
run record. Bodies follow tests/kb/test_b15_tiebreak.py; the wires carry
no summary, so the merge score here is the title+body overlap alone.
"""

import json
import re

from openpyxl import Workbook

from engine.cli.kb import _print_ingest_report
from engine.cli.main import main
from engine.kb import KBStore
from engine.kb.identity import kb_id_for
from engine.kb.ingest import IngestReport

BUYER = "Northwind Regional Health"
WIRE = json.dumps({"chunk_annotations": [], "qa_pairs": [], "identifiers": [],
                   "client_descriptor": "a regional health system"})
REVIEW = json.dumps({"identifiers": []})
BODY = ("The migration factory converts legacy balances wave by wave "
        "with penny-level reconciliation against the source ledger.")
BODY_VARIANT = ("The migration factory converts legacy balances wave by "
                "wave with cent-level reconciliation against the source "
                "ledger.")
BODY_NEW = ("Hypercare runs for six weeks after go-live with a named lead "
            "on every shift and a defect triage each morning.")
MERGE_LINE = re.compile(
    r"^  merged: (kb_[0-9a-f]{10}) -> (kb_[0-9a-f]{10}) "
    r"\(score 0\.\d\d; the new card survives\)$")


def _ids(kb_root) -> list[str]:
    return sorted(c["kb_id"] for c in KBStore(kb_root).list_cards())


def _md(path, bodies):
    path.write_text("\n\n".join(f"## Data Migration\n\n{b}" for b in bodies)
                    + "\n", encoding="utf-8")
    return path


def _args(tmp_path, file, *extra):
    wire, review = tmp_path / "wire.json", tmp_path / "review.json"
    wire.write_text(WIRE, encoding="utf-8")
    review.write_text(REVIEW, encoding="utf-8")
    return ["kb", "ingest", "--kb", str(tmp_path / "kb"), "--file", str(file),
            "--client", BUYER, "--pursuit", "pur_rep", "--date", "2026-01-01",
            "--wire", str(wire), "--reviewer-wire", str(review), *extra]


def _seed_then_second(tmp_path, capsys, *extra):
    """Doc 1 (lost): one body. Doc 2 (won): the same body again — an exact
    duplicate; a one-word variant — a near duplicate the won outcome lets
    survive; a new body. Returns the second door call's exit code."""
    first = _md(tmp_path / "doc1.md", [BODY])
    assert main(_args(tmp_path, first, "--outcome", "lost")) == 0
    capsys.readouterr()  # doc 1's own lines are not under test
    second = _md(tmp_path / "doc2.md", [BODY, BODY_VARIANT, BODY_NEW])
    return main(_args(tmp_path, second, "--outcome", "won", *extra))


def test_kb_ingest_prints_merges_and_skips_by_id(tmp_path, capsys):
    assert _seed_then_second(tmp_path, capsys) == 0
    lines = capsys.readouterr().out.splitlines()
    assert re.fullmatch(r"\S+: ingested, \+2 cards, 1 merged, 1 skipped", lines[0])
    merge = MERGE_LINE.fullmatch(lines[1])
    assert merge and merge.groups() == (kb_id_for(BODY), kb_id_for(BODY_VARIANT))
    assert lines[2] == (f"  skipped: {kb_id_for(BODY)} "
                        "(identical content already in the store)")
    assert len(lines) == 3  # no flag, no reconciliation on a first ingest
    assert _ids(tmp_path / "kb") == sorted(
        [kb_id_for(BODY_VARIANT), kb_id_for(BODY_NEW)])
    for line in lines:  # ids only — no body text reaches the terminal
        assert "migration factory" not in line.lower()


def test_kb_ingest_prior_merge_prints_without_a_score(tmp_path, capsys):
    assert _seed_then_second(tmp_path, capsys) == 0
    capsys.readouterr()
    # the same bytes again: a re-ingest — the absorbed body is recognised
    # through the fold, the two surviving cards are exact duplicates
    assert main(_args(tmp_path, tmp_path / "doc2.md", "--outcome", "won")) == 0
    lines = capsys.readouterr().out.splitlines()
    assert re.fullmatch(r"\S+: ingested, \+0 cards, 1 merged, 2 skipped", lines[0])
    assert lines[1] == (f"  merged: {kb_id_for(BODY)} -> {kb_id_for(BODY_VARIANT)} "
                        "(absorbed in an earlier ingest)")
    assert lines[2:4] == [
        f"  skipped: {kb_id_for(BODY_VARIANT)} (identical content already in the store)",
        f"  skipped: {kb_id_for(BODY_NEW)} (identical content already in the store)"]
    assert lines[4] == "  reconciliation: 3 matched, 0 drifted, 0 created, 0 orphaned"


def test_kb_ingest_dry_run_prints_would_lines_and_leaves_only_a_run_record(
        tmp_path, capsys):
    assert _seed_then_second(tmp_path, capsys, "--dry-run") == 0
    out = capsys.readouterr().out
    lines = out.splitlines()
    assert lines[0].startswith("dry run — nothing written: ")
    assert lines[0].endswith(": would be ingested, +2 cards, 1 merged, 1 skipped")
    assert lines[1].startswith(f"  would merge: {kb_id_for(BODY)} -> ")
    assert lines[2].startswith(f"  would skip: {kb_id_for(BODY)} ")
    kb = tmp_path / "kb"
    assert lines[3] == f"  run record: {kb / 'runs' / 'run_0002'}"
    assert len(lines) == 4
    assert _ids(kb) == [kb_id_for(BODY)]  # doc 1 only
    assert sorted(p.name for p in (kb / "runs").iterdir()) == ["run_0001",
                                                                "run_0002"]
    assert len(list(kb.glob("canonical/*.json"))) == 1  # doc 1's model only
    assert len(list(kb.glob("restricted/sources/*.src"))) == 1


def test_kb_ingest_prints_the_degraded_flag_through_the_door(tmp_path, capsys):
    wb = Workbook()
    ws = wb.active
    ws.title = "2. Delivery"
    ws.append(["Ref", "Question", "Response"])
    ws.append(["1.1", "Describe your company history.",
               "Founded in 1998 and privately held, with offices in four regions."])
    ws.append(["1.2", "Describe a superseded draft answer.",
               "An earlier draft kept on a hidden row that must never ride along."])
    ws.row_dimensions[3].hidden = True
    xlsx = tmp_path / "resp.xlsx"
    wb.save(xlsx)
    capsys.readouterr()
    assert main(_args(tmp_path, xlsx)) == 0
    out = capsys.readouterr().out.splitlines()
    assert re.fullmatch(r"\S+: ingested, \+1 cards", out[0])
    assert out[1] == ("  flagged: degraded extraction — content was lost at read; "
                      "these cards carry extraction_status degraded")


def test_report_formatter_covers_every_line_shape(capsys):
    """The lines the integration tests cannot reach cheaply: the media
    flag with a count, a dry-run proposal count, the prior shape without
    a score beside the two scored shapes, the reconciliation buckets."""
    report = IngestReport(
        doc_id="doc_x", status="ingested", cards_written=["kb_aaaaaaaaaa"],
        merged=[{"survivor": "kb_bbbbbbbbbb", "absorbed": "kb_cccccccccc",
                 "prior": True},
                {"survivor": "kb_aaaaaaaaaa", "absorbed": "kb_dddddddddd",
                 "score": 0.8312, "kept": "new"},
                {"survivor": "kb_eeeeeeeeee", "absorbed": "kb_ffffffffff",
                 "score": 0.5, "kept": "existing"}],
        skipped=["kb_gggggggggg"], proposals=["prop_1", "prop_2"],
        extraction_flagged=True, media_flagged=True,
        reconciliation={"created": 1, "matched": 2, "drifted": 0,
                        "orphaned": 0},
        dry_run=True)
    _print_ingest_report(report, run_dir="kb/runs/run_0007", images=2)
    assert capsys.readouterr().out.splitlines() == [
        "dry run — nothing written: doc_x: would be ingested, +1 cards, "
        "3 merged, 1 skipped, 2 proposals",
        "  would merge: kb_cccccccccc -> kb_bbbbbbbbbb (absorbed in an earlier ingest)",
        "  would merge: kb_dddddddddd -> kb_aaaaaaaaaa (score 0.83; the new card survives)",
        "  would merge: kb_ffffffffff -> kb_eeeeeeeeee (score 0.50; the existing card survives)",
        "  would skip: kb_gggggggggg (identical content already in the store)",
        "  flagged: degraded extraction — content was lost at read; "
        "these cards carry extraction_status degraded",
        "  flagged: 2 embedded images — identity the text scan cannot see",
        "  reconciliation: 2 matched, 0 drifted, 1 created, 0 orphaned",
        "  run record: kb/runs/run_0007",
    ]
    report.dry_run, report.media_flagged = False, False
    _print_ingest_report(report, run_dir=None)
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "doc_x: ingested, +1 cards, 3 merged, 1 skipped, 2 proposals"
    assert lines[1].startswith("  merged: ") and lines[4].startswith("  skipped: ")
    assert not any(line.startswith("  run record") for line in lines)
