"""P29a step a4 (P1-49): the gap→card spawner is ONE door — every caller
(Gate 0's opt-in, the ping lane's opt-in, the accept-time route) cleans
and scans through it; a residue refuses by location and the record
names the block; a proposal another door opened dirty is voided at the
accept-time re-check; a card mints only from a scanned body.
"""

import json

import pytest

from engine.flywheel.proposals import ProposalStore
from engine.intake.gate import approve_gate0
from engine.kb import KBStore
from engine.kb.curation import CurationRefused, merge_batch
from engine.llm import effective_config
from engine.runlog import RunLogger
from engine.version import engine_version
from engine.web.learn import _route_gaps
from engine.web.pings import PingLane
from engine.workspace import PursuitDir
from tests.intake.fixtures.packages import _wire_from_prompt, run_package

AT = "2026-09-10T09:00:00Z"
BUYER = "Northwind Regional Health"  # the intake fixture's buyer name
# An acronym: substitution never touches it, the scan is built to catch it.
DIRTY = "NRH prefers weekly steering calls."
CLEAN = (f"{BUYER}'s program lead is reachable at ops@northwind.example "
         "during hypercare.")


def _starving(prompt: str) -> str:
    wire = json.loads(_wire_from_prompt(prompt))
    wire["procurement"].pop("what_is_bought", None)
    return json.dumps(wire)


def _gate_log(pursuit):
    log = RunLogger(pursuit.root, pursuit.new_run_id(), pursuit.pursuit_id)
    log.run_start(mode="dry_run", engine_version=engine_version(),
                  config=effective_config(), kb_snapshot="kb@empty")
    return log


def _gate0_answer(tmp_path, answer: str):
    pursuit, _ = run_package(tmp_path / "p", "pdf",
                             script={"intake_analyst": _starving})
    kb_root = tmp_path / "kb"
    brief = pursuit.read_artifact("brief.json")
    gap_id = brief["intake"]["gaps"][0]["gap_id"]
    log = _gate_log(pursuit)
    result = approve_gate0(
        pursuit, log, decision="approved_with_edits", actor="Pat Lead",
        at=AT, kb_root=kb_root,
        answers=[{"gap_id": gap_id, "answer": answer, "propose_card": True}])
    log.run_end(status="completed")
    return pursuit, kb_root, gap_id, result


def test_gate0_opt_in_refuses_a_residue_by_location(tmp_path):
    pursuit, kb_root, gap_id, result = _gate0_answer(tmp_path, DIRTY)
    assert result.proposals == []
    assert result.blocked == [{"gap_id": gap_id, "locations": ["answer"]}]
    assert ProposalStore(kb_root).list() == []
    # the ANSWER stands on the brief — only the card was refused
    brief = pursuit.read_artifact("brief.json")
    gap = next(g for g in brief["intake"]["gaps"] if g["gap_id"] == gap_id)
    assert gap["status"] == "answered" and gap["answer"] == DIRTY


def test_gate0_opt_in_cleans_the_question_and_the_answer(tmp_path):
    _pursuit, kb_root, _gap_id, result = _gate0_answer(tmp_path, CLEAN)
    assert result.blocked == [] and len(result.proposals) == 1
    proposal = ProposalStore(kb_root).read(result.proposals[0])
    body = proposal["diff"]["body"]["after"]
    assert "[CLIENT]" in body and "[CONTACT]" in body
    assert "Northwind" not in json.dumps(proposal)
    assert "@" not in body


PLAN = {
    "pursuit_id": "pur_onedoor", "path": "A_designated", "status": "approved",
    "sections": [{
        "section_id": "sec-01", "title": "Approach",
        "gaps": [{"gap_id": "gap_od_001", "slot_id": "s-a01",
                  "kind": "no_content", "status": "open",
                  "question_to_human": "What is our conversion stance?"}]}],
}


class _Sink:
    def emit(self, *a, **k):
        return 0


def test_ping_opt_in_refuses_a_residue_by_location(tmp_path):
    pursuit = PursuitDir(tmp_path, "pur_onedoor")
    (pursuit.root / "brief.json").write_text(
        json.dumps({"buyer": {"name": BUYER}}), encoding="utf-8")
    KBStore(tmp_path / "kb")
    plan = json.loads(json.dumps(PLAN))
    lane = PingLane(pursuit)
    record = lane.ping(_Sink(), plan, gap_id="gap_od_001", route_to="sme",
                       at=AT, actor="Astrid")
    out = lane.answer(_Sink(), plan, ping_id=record["ping_id"], answer=DIRTY,
                      at=AT, actor="Astrid", propose_card=True,
                      kb_root=tmp_path / "kb")
    assert "proposal" not in out
    assert out["blocked"] == [{"gap_id": "gap_od_001", "locations": ["answer"]}]
    assert ProposalStore(tmp_path / "kb").list() == []
    assert plan["sections"][0]["gaps"][0]["answer"] == DIRTY  # the answer stands


def test_a_card_mints_only_from_a_scanned_body(tmp_path):
    """The accept door's own belt (structured classes, unconditional):
    a new_card body carrying a contact detail refuses, nothing mints,
    and the log line names the abort."""
    store = KBStore(tmp_path / "kb")
    pid = ProposalStore(store.root).open(
        source={"door": "gap_answer", "pursuit_id": "pur_x", "gap_id": "g1"},
        target="fact_sheet", kind="new_card", at=AT,
        diff={"title": {"after": "Who to call"},
              "body": {"after": "Q: who?\nA: reach (555) 214-8890 any time"},
              "layer": {"after": "fact_sheet"}, "grain": {"after": "atom"},
              "content_origin": {"after": "source_text"}})["proposal_id"]
    with pytest.raises(CurationRefused, match="identifier residue at"):
        merge_batch(store, [pid], operator="Sam", at=AT,
                    fills={pid: {"owner": "Sam", "verified_date": "2026-09-10"}})
    assert store.list_cards() == []
    assert ProposalStore(store.root).read(pid)["status"] == "proposed"


def test_the_accept_time_re_check_voids_a_dirty_proposal(tmp_path):
    """A proposal another door opened raw (the pre-P29a Gate 0 / ping
    doors) is found at accept time, voided with a curation-log line,
    and the gap is re-proposed clean — the control proven at the door
    that used to trust `already`."""
    pursuit = PursuitDir(tmp_path, "pur_recheck")
    (pursuit.root / "brief.json").write_text(json.dumps({
        "buyer": {"name": BUYER},
        "intake": {"gaps": [{"gap_id": "gap_rc_01", "status": "answered",
                             "question_to_human": "Cadence?",
                             "answer": "Weekly steering calls with the PMO.",
                             "answered_by": "Pat"}]}}), encoding="utf-8")
    store = KBStore(tmp_path / "kb")
    proposals = ProposalStore(store.root)
    dirty = proposals.open(
        source={"door": "gap_answer", "pursuit_id": "pur_recheck",
                "gap_id": "gap_rc_01"},
        target="fact_sheet", kind="new_card", at=AT,
        diff={"title": {"after": "Cadence?"},
              "body": {"after": f"Q: Cadence?\nA: {DIRTY}"},
              "layer": {"after": "fact_sheet"}, "grain": {"after": "atom"},
              "content_origin": {"after": "source_text"}})["proposal_id"]
    opened, blocked = _route_gaps(pursuit, store.root, at=AT, by="Jordan",
                                  identifiers={BUYER: "CLIENT"})
    voided = proposals.read(dirty)
    assert voided["status"] == "voided"
    assert voided["decided"]["decision"] == "voided"
    assert voided["decided"]["by"] == "learn:Jordan"
    assert blocked == [{"gap_id": "gap_rc_01", "proposal_id": dirty,
                        "locations": ["body.after"]}]
    assert len(opened) == 1 and opened[0] != dirty
    fresh = proposals.read(opened[0])
    assert fresh["status"] == "proposed"
    assert "NRH" not in fresh["diff"]["body"]["after"]
    lines = [json.loads(l) for l in
             (store.root / "curation-log.jsonl").read_text().splitlines()]
    assert lines[-1]["voided"] == [dirty] and "residue" in lines[-1]["reason"]
    # idempotent: a second pass finds the clean one standing
    again, blocked_again = _route_gaps(pursuit, store.root, at=AT,
                                       by="Jordan",
                                       identifiers={BUYER: "CLIENT"})
    assert again == [] and blocked_again == []
