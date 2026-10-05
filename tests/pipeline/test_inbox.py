"""P32c: engine.pipeline.inbox — the inbox rule the web advance job and
the replay runner share (P16/C5's ONE declared-target resolver, now with
two callers). Behaviour and messages are the web door's, verbatim."""

import json

import pytest

from engine.contracts import ContractError
from engine.pipeline.inbox import package_from_inbox, resolve_targets


def _inbox(root, names, roles=None):
    inbox = root / "inbox"
    inbox.mkdir(exist_ok=True)
    for name in names:
        (inbox / name).write_bytes(b"x")
    if roles is not None:
        (inbox / "roles.json").write_text(json.dumps(roles), encoding="utf-8")
    return inbox


def test_an_undeclared_inbox_keeps_the_first_workbook_rule(tmp_path):
    inbox = _inbox(tmp_path, ["b.xlsx", "a.xlsx"])
    (inbox / "ramble.md").write_text("context", encoding="utf-8")
    assert resolve_targets(tmp_path) == {"targets": [inbox / "a.xlsx"],
                                         "core": None, "declared": False}
    package = package_from_inbox("pur_x", tmp_path)
    assert package.pursuit_id == "pur_x" and package.ramble == "context"
    assert [(d.path.name, d.kind) for d in package.docs] == [("a.xlsx",
                                                               "rfp_main")]


def test_a_declared_inbox_is_authoritative(tmp_path):
    inbox = _inbox(tmp_path, ["rfp.pdf", "answers.docx", "notes.txt"],
                   roles={"rfp.pdf": "core", "answers.docx": "target",
                          "notes.txt": "supplemental"})
    assert resolve_targets(tmp_path) == {"targets": [inbox / "answers.docx"],
                                         "core": inbox / "rfp.pdf",
                                         "declared": True}
    package = package_from_inbox("pur_x", tmp_path)
    assert [(d.path.name, d.kind, d.role) for d in package.docs] == [
        ("answers.docx", "other", "target"), ("rfp.pdf", "rfp_main", "core")]
    assert package.ramble == ""


def test_refusals_are_typed_and_say_what_to_do(tmp_path):
    inbox = _inbox(tmp_path, [])
    with pytest.raises(ContractError, match="no .xlsx in inbox/"):
        package_from_inbox("pur_x", tmp_path)
    (inbox / "roles.json").write_text(json.dumps({"gone.docx": "target"}),
                                      encoding="utf-8")
    with pytest.raises(ContractError, match=r"declared target\(s\) missing"):
        resolve_targets(tmp_path)
    (inbox / "notes.txt").write_bytes(b"x")
    (inbox / "roles.json").write_text(
        json.dumps({"notes.txt": "supplemental"}), encoding="utf-8")
    with pytest.raises(ContractError, match="names no readable documents"):
        package_from_inbox("pur_x", tmp_path)
    (inbox / "a.docx").write_bytes(b"x")
    (inbox / "roles.json").write_text(json.dumps({"a.docx": "target"}),
                                      encoding="utf-8")
    with pytest.raises(ContractError, match="role=core"):
        package_from_inbox("pur_x", tmp_path)
