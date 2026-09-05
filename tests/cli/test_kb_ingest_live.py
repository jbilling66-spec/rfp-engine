"""P1-45 (P28): the production ingest door has a live caller. `--live`
refuses by construction without RFP_LIVE=1 and mints nothing; offline the
door takes two scripted replies, one per reader, and refuses by name when
one is missing.
"""

import json

import pytest

from engine.cli.main import main

CLIENT = "Foxfire Municipal Utilities"
DOC = ("# DOC:live_doc\n\n## Data Migration\n\nFoxfire Municipal Utilities "
       "engaged us for a billing migration; reach ops@foxfire.example or "
       "(555) 214-8890 during hypercare.\n")
WIRE = json.dumps({"chunk_annotations": [], "qa_pairs": [],
                   "identifiers": [{"value": CLIENT, "type": "CLIENT"}],
                   "client_descriptor": "a municipal utility"})
REVIEW = json.dumps({"identifiers": [{"value": CLIENT, "type": "CLIENT"}]})


def _args(tmp_path, *extra):
    doc = tmp_path / "live_doc.md"
    doc.write_text(DOC, encoding="utf-8")
    return ["kb", "ingest", "--kb", str(tmp_path / "kb"), "--file", str(doc),
            "--client", CLIENT, "--pursuit", "pur_live", "--date",
            "2026-01-01", *extra]


def test_live_refuses_without_the_flag_and_mints_nothing(tmp_path, capsys,
                                                         monkeypatch):
    monkeypatch.delenv("RFP_LIVE", raising=False)
    assert main(_args(tmp_path, "--live")) == 1
    err = capsys.readouterr().err
    assert "ingest --live refused" in err and "RFP_LIVE=1" in err
    assert not (tmp_path / "kb" / "runs").exists()
    assert not list((tmp_path / "kb").glob("cards/*.md"))


def test_live_and_a_scripted_wire_are_mutually_exclusive(tmp_path):
    with pytest.raises(SystemExit):
        main(_args(tmp_path, "--live", "--wire", "x"))


def test_live_refuses_an_offline_reviewer_wire(tmp_path, capsys):
    assert main(_args(tmp_path, "--live", "--reviewer-wire", "x")) == 1
    assert "--reviewer-wire is an offline flag" in capsys.readouterr().err


def test_offline_needs_both_wires_by_name(tmp_path, capsys):
    wire = tmp_path / "wire.json"
    wire.write_text(WIRE, encoding="utf-8")
    assert main(_args(tmp_path, "--wire", str(wire))) == 1
    assert "--reviewer-wire is required" in capsys.readouterr().err
    assert main(_args(tmp_path)) == 1
    assert "--wire and --reviewer-wire" in capsys.readouterr().err
    assert not (tmp_path / "kb" / "runs").exists()


def test_two_wires_ingest_with_typed_placeholders(tmp_path, capsys):
    wire = tmp_path / "wire.json"
    wire.write_text(WIRE, encoding="utf-8")
    review = tmp_path / "review.json"
    review.write_text(REVIEW, encoding="utf-8")
    assert main(_args(tmp_path, "--wire", str(wire),
                      "--reviewer-wire", str(review))) == 0
    assert "ingested" in capsys.readouterr().out
    cards = " ".join(p.read_text(encoding="utf-8")
                     for p in (tmp_path / "kb" / "cards").glob("*.md"))
    assert "[CLIENT]" in cards and "[CONTACT]" in cards
    assert "foxfire.example" not in cards and "214-8890" not in cards
