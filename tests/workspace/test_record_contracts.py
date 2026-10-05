"""P32b / P1-8 narrow (B145): the four free-form records go through the
contract door on the way OUT (commit 5) and are validated on the way IN
by the readers that already decide what a bad record means (commit 6).

Writer side: a bare `write_json` is failed under the test, so every lane
proves it writes through `write_artifact`; a pending entry carrying a key
the schema never wrote is refused at write and the store is untouched."""

import json

import pytest

from engine.contracts import ContractError, validate
from engine.llm import effective_config
from engine.runlog import RunLogger
from engine.version import engine_version
from engine.web.addenda import AddendumLane
from engine.web.events import EventsLane
from engine.workspace.pursuit import PursuitDir
from tests.extraction.fakes import FakeExtractionBackend
from tests.intake.fixtures.packages import run_package
from tests.intake.test_brief_backend import _pdf_twin_view
from tests.revision.fixtures.rounds import (ROUND_AT, add_comment,
                                            run_one_round, validated_pursuit)


def _bare_write_fails(monkeypatch):
    def bare(self, name, obj):
        raise AssertionError(f"bare write_json({name!r}) — the record has a "
                             "contract; write through write_artifact")
    monkeypatch.setattr(PursuitDir, "write_json", bare)


def _first_section(pursuit):
    return pursuit.read_artifact("drafts/draft.json")["sections"][0]["section_id"]


def test_the_pending_store_is_written_through_the_contract_door(
        tmp_path, monkeypatch):
    pursuit = validated_pursuit(tmp_path)
    _bare_write_fails(monkeypatch)
    entry = add_comment(pursuit, _first_section(pursuit), "Tighten it.")
    EventsLane(pursuit).mark_pending(entry["cid"], included_by="Jordan",
                                     included_at=ROUND_AT)
    stored = json.loads((pursuit.root / "events" / "pending.json").read_text())
    validate("pending_comments", stored)
    assert stored["pending"][0]["included_by"] == "Jordan"


def test_a_pending_entry_the_schema_never_wrote_is_refused_at_write(tmp_path):
    pursuit = validated_pursuit(tmp_path)
    sid = _first_section(pursuit)
    add_comment(pursuit, sid, "First.")
    before = (pursuit.root / "events" / "pending.json").read_bytes()
    with pytest.raises(ContractError, match="pending_comments.*mood"):
        EventsLane(pursuit).add_pending(
            kind="comment", section_id=sid, actor="Pat", actor_role="pursuit_lead",
            at=ROUND_AT, text="Second.", mood="cheerful")
    assert (pursuit.root / "events" / "pending.json").read_bytes() == before


def test_the_round_record_is_written_through_the_contract_door(
        tmp_path, monkeypatch):
    pursuit = validated_pursuit(tmp_path)
    add_comment(pursuit, _first_section(pursuit), "Name the benefit earlier.")
    _bare_write_fails(monkeypatch)
    report, _ = run_one_round(tmp_path, pursuit)
    assert report.status == "complete", report.warnings
    record = json.loads((pursuit.root / "revisions" / "round_1.json").read_text())
    validate("revision_round", record)


def test_the_addendum_meta_is_written_through_the_contract_door(
        tmp_path, monkeypatch):
    pursuit = validated_pursuit(tmp_path)
    _bare_write_fails(monkeypatch)
    lane = AddendumLane(pursuit)
    meta = lane.store(filename="amendment-1.txt", body=b"Amendment one: scope.",
                      at=ROUND_AT, actor="Pat", slots_by_id=None)
    log = RunLogger(pursuit.root, pursuit.new_run_id(), pursuit.pursuit_id)
    log.run_start(mode="dry_run", engine_version=engine_version(),
                  config=effective_config(), kb_snapshot="kb@empty")
    decided = lane.decide(log, aid=meta["addendum_id"], decision="replan",
                          note="scope moved", at=ROUND_AT, actor="Pat")
    log.run_end(status="completed")
    on_disk = json.loads((pursuit.root / "addenda" / meta["addendum_id"]
                          / "meta.json").read_text())
    validate("addendum_meta", on_disk)
    assert on_disk == decided and on_disk["decision"] == "replan"


def test_the_extraction_record_is_written_through_the_contract_door(
        tmp_path, monkeypatch):
    _bare_write_fails(monkeypatch)
    fake = FakeExtractionBackend({"pdf-twin.pdf": _pdf_twin_view()})
    pursuit, report = run_package(tmp_path, "pdf", extraction=fake)
    assert report.status == "complete"
    validate("extraction_record",
             json.loads((pursuit.root / "extraction.json").read_text()))


# --- readers (commit 6a): the assembly render names a draft that fails -----

def test_the_render_refuses_a_draft_that_fails_its_schema_by_name(tmp_path):
    """`docx._load` is the one reader behind both renders; with the kind
    passed, a draft that parses but breaks its contract refuses by file
    name before any document is built."""
    from engine.assembly import docx as docx_mod
    pursuit = validated_pursuit(tmp_path)
    draft = pursuit.root / "drafts" / "draft.json"
    envelope = json.loads(draft.read_text())
    envelope["sections"][0]["status"] = "mangled"
    draft.write_text(json.dumps(envelope), encoding="utf-8")
    with pytest.raises(ContractError, match="drafts/draft.json fails its schema"):
        docx_mod._load(pursuit)


# --- readers (commit 6b): the pending store refuses, never defaults --------

def test_a_pending_store_that_fails_its_schema_is_refused_not_defaulted(tmp_path):
    """B145 §3c/§3d: the pre-monotonic shape (no next_cid) used to be
    silently defaulted; the store holds human work, so a file that fails
    its contract is a typed refusal at every door and is never rewritten."""
    pursuit = validated_pursuit(tmp_path)
    store = pursuit.root / "events" / "pending.json"
    store.write_text(json.dumps({"pending": []}), encoding="utf-8")
    lane = EventsLane(pursuit)
    with pytest.raises(ContractError, match="events/pending.json fails its schema"):
        lane.pending()
    with pytest.raises(ContractError, match="fails its schema"):
        add_comment(pursuit, _first_section(pursuit), "Never lands.")
    assert json.loads(store.read_text(encoding="utf-8")) == {"pending": []}
