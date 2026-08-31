"""The gap→card link (P15/C10, B69 §7): an ANSWERED intake gap may
spawn a new_card proposal through the steward door — opt-in, never
automatic, and NOTHING enters the corpus until a steward accepts with
owner/verified_date (the P13/C15 fill machinery, reused not rebuilt).
This is the missing link between "a human answered a question" and
"the corpus learns", so the same question stops being re-asked."""

import json

import pytest

from engine.contracts import ContractError
from engine.flywheel.proposals import ProposalStore
from engine.intake.gate import approve_gate0
from engine.kb import KBStore
from engine.kb.curation import CurationRefused, merge_batch
from engine.llm import effective_config
from engine.runlog import RunLogger
from engine.version import engine_version
from tests.intake.fixtures.packages import _wire_from_prompt, run_package

GATE_AT = "2026-08-28T09:00:00Z"


def _starving(prompt: str) -> str:
    wire = json.loads(_wire_from_prompt(prompt))
    wire["procurement"].pop("what_is_bought", None)
    return json.dumps(wire)


def _gate_log(pursuit):
    log = RunLogger(pursuit.root, pursuit.new_run_id(), pursuit.pursuit_id)
    log.run_start(mode="dry_run", engine_version=engine_version(),
                  config=effective_config(), kb_snapshot="kb@empty")
    return log


@pytest.fixture()
def gapped(tmp_path):
    pursuit, _ = run_package(tmp_path / "p", "pdf",
                             script={"intake_analyst": _starving})
    return pursuit, tmp_path / "kb"


def _answer(pursuit, kb_root, *, propose: bool):
    brief = pursuit.read_artifact("brief.json")
    gap_id = brief["intake"]["gaps"][0]["gap_id"]
    log = _gate_log(pursuit)
    result = approve_gate0(
        pursuit, log, decision="approved_with_edits", actor="Pat Lead",
        at=GATE_AT, kb_root=kb_root,
        answers=[{"gap_id": gap_id,
                  "answer": "Managed ERP transition services",
                  **({"propose_card": True} if propose else {})}])
    log.run_end(status="completed")
    return result


def test_opt_in_spawns_a_proposal_through_the_door(gapped):
    pursuit, kb_root = gapped
    result = _answer(pursuit, kb_root, propose=True)
    assert len(result.proposals) == 1
    proposal = ProposalStore(kb_root).read(result.proposals[0])
    assert proposal["status"] == "proposed"
    assert proposal["kind"] == "new_card"
    assert proposal["source"]["door"] == "gap_answer"
    assert proposal["source"]["operator"] == "Pat Lead"
    assert proposal["source"]["pursuit_id"] == pursuit.pursuit_id
    body = proposal["diff"]["body"]["after"]
    assert "Managed ERP transition services" in body


def test_nothing_enters_the_corpus_without_a_steward(gapped):
    """THE named anti-poisoning test (S4/T3): the proposal exists, the
    STORE is untouched; acceptance without the steward's owner and
    verified_date REFUSES; with them, the card mints — human-vouched."""
    pursuit, kb_root = gapped
    result = _answer(pursuit, kb_root, propose=True)
    store = KBStore(kb_root)
    assert store.snapshot() == "kb@empty"  # the answer taught NOTHING yet

    pid = result.proposals[0]
    with pytest.raises(CurationRefused, match="owner and"):
        merge_batch(store, [pid], operator="Sam Steward", at=GATE_AT)
    assert store.snapshot() == "kb@empty"  # the refusal wrote nothing

    out = merge_batch(store, [pid], operator="Sam Steward", at=GATE_AT,
                      fills={pid: {"owner": "Sam Steward",
                                   "verified_date": "2026-08-28"}})
    assert out["proposal_ids"] == [pid]
    assert store.snapshot() != "kb@empty"  # NOW the corpus learned


def test_without_the_flag_no_proposal_exists(gapped):
    pursuit, kb_root = gapped
    result = _answer(pursuit, kb_root, propose=False)
    assert result.proposals == []
    assert ProposalStore(kb_root).list() == []


def test_flag_without_kb_root_refuses_never_drops(tmp_path):
    pursuit, _ = run_package(tmp_path, "pdf",
                             script={"intake_analyst": _starving})
    gap_id = pursuit.read_artifact("brief.json")["intake"]["gaps"][0][
        "gap_id"]
    log = _gate_log(pursuit)
    with pytest.raises(ContractError, match="honored or refused"):
        approve_gate0(pursuit, log, decision="approved_with_edits",
                      actor="Pat Lead", at=GATE_AT,
                      answers=[{"gap_id": gap_id, "answer": "x",
                                "propose_card": True}])
    log.run_end(status="failed")
