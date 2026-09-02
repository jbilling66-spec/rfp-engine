"""P25 item 6 (P0-8, P2-25): the office-zip guard refuses a bomb before
any parser inflates it; the committed twins pass; and defusedxml is live
in openpyxl, so an internal-entity bomb is a typed refusal too."""

import io
import zipfile
from pathlib import Path

import openpyxl
import pytest

import importlib
from engine.intake.extract import UnreadableRfp, extract
from engine.structure.zipguard import ZipGuardError, check_office_zip

extract_mod = importlib.import_module("engine.intake.extract")

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _member_bomb(path: Path, members: int) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        for i in range(members):
            zf.writestr(f"m/{i}.xml", "<a/>")
    return path


def _size_bomb(path: Path, mib: int) -> Path:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        with zf.open("xl/worksheets/sheet1.xml", "w") as member:
            block = b"\0" * (1024 * 1024)
            for _ in range(mib):
                member.write(block)
    return path


def test_committed_twins_pass_the_guard():
    for name in ("demo-twin.xlsx", "qform-twin.docx"):
        report = check_office_zip(FIXTURES / name)
        assert 0 < report["members"] < 200


def test_member_and_size_ceilings_refuse_before_the_parser(tmp_path,
                                                          monkeypatch):
    bomb = _member_bomb(tmp_path / "members.xlsx", 10_050)
    with pytest.raises(ZipGuardError, match="members"):
        check_office_zip(bomb)
    big = _size_bomb(tmp_path / "big.xlsx", 260)
    with pytest.raises(ZipGuardError, match="uncompressed"):
        check_office_zip(big)
    assert big.stat().st_size < 2 * 1024 * 1024  # a real bomb: tiny on disk

    def never(*a, **k):
        raise AssertionError("the parser ran on a refused container")

    monkeypatch.setattr(extract_mod, "load_workbook", never)
    with pytest.raises(UnreadableRfp, match="ceiling"):
        extract(big)
    not_a_zip = tmp_path / "plain.docx"
    not_a_zip.write_bytes(b"this is not a zip container")
    monkeypatch.setattr(extract_mod, "Document", never, raising=False)
    with pytest.raises(UnreadableRfp, match="not a zip"):
        extract(not_a_zip)


def test_defusedxml_is_live_so_an_entity_bomb_is_a_refusal(tmp_path):
    assert openpyxl.DEFUSEDXML is True, (
        "defusedxml is not installed — openpyxl parses with stdlib "
        "ElementTree and internal entities expand (P2-25)")
    source = zipfile.ZipFile(FIXTURES / "demo-twin.xlsx")
    bomb = tmp_path / "laughs.xlsx"
    with zipfile.ZipFile(bomb, "w", compression=zipfile.ZIP_DEFLATED) as out:
        for info in source.infolist():
            data = source.read(info.filename)
            if info.filename.startswith("xl/worksheets/sheet") and \
                    info.filename.endswith(".xml"):
                head, _, rest = data.partition(b"?>")
                data = (head + b"?><!DOCTYPE x [<!ENTITY a \"aaaaaaaaaa\">"
                        b"<!ENTITY b \"&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;\">"
                        b"<!ENTITY c \"&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;\">]>"
                        + rest.replace(b"<sheetData>", b"<sheetData><row r=\"1\">"
                                       b"<c r=\"A1\" t=\"inlineStr\"><is><t>&c;"
                                       b"</t></is></c></row>", 1))
            out.writestr(info, data)
    with pytest.raises(UnreadableRfp):
        extract(bomb)
