"""Run-log shape for the research run: stage pairs, exactly two mid-tier
agent calls (R1 literal), artifact records for the consumed pack and the
rewritten brief, every derived topic logged verbatim as a kb.query (S6:
queries are logged), seq gapless, totals reconcile."""

import hashlib

import pytest

from engine.runlog import assert_seq_gapless, read_run
from tests.research.fixtures.pursuits import EXPECTED_TOPICS, run_research_package


@pytest.fixture(scope="module")
def airgapped(tmp_path_factory):
    return run_research_package(tmp_path_factory.mktemp("runlog"))


def _records(pursuit):
    return read_run(pursuit.root / "runs" / "run_0002" / "run.jsonl")


def test_stage_pairs_and_gapless_seq(airgapped):
    pursuit, _ = airgapped
    records = _records(pursuit)
    assert_seq_gapless(records)
    stages = [(r["record_type"], r.get("stage")) for r in records
              if r["record_type"] in ("stage_start", "stage_end")]
    assert stages == [
        ("stage_start", "research_internal"), ("stage_end", "research_internal"),
        ("stage_start", "research_external"), ("stage_end", "research_external"),
    ]


def test_exactly_two_mid_tier_agent_calls(airgapped):
    pursuit, _ = airgapped
    calls = [r for r in _records(pursuit) if r["record_type"] == "agent_call"]
    assert [(c["agent"], c["stage"]) for c in calls] == [
        ("internal_researcher", "research_internal"),
        ("external_researcher", "research_external"),
    ]
    assert all(c["model_tier"] == "mid" for c in calls)
    run_end = _records(pursuit)[-1]
    assert run_end["run"]["totals"]["agent_calls"] == 2


def test_artifact_records_pack_and_brief(airgapped):
    pursuit, _ = airgapped
    artifacts = [r["artifact"] for r in _records(pursuit)
                 if r["record_type"] == "artifact"]
    by_kind = {a["kind"]: a for a in artifacts}
    assert set(by_kind) == {"research_pack", "bid_brief"}
    pack = by_kind["research_pack"]
    assert "inbox" in pack["path"]
    assert pack["sha256"] == hashlib.sha256(
        (pursuit.root / "inbox" / "research-pack.md").read_bytes()).hexdigest()
    brief = by_kind["bid_brief"]
    assert brief["sha256"] == hashlib.sha256(
        (pursuit.root / "brief.json").read_bytes()).hexdigest()


def test_every_topic_is_a_logged_query(airgapped):
    pursuit, _ = airgapped
    searches = [r["kb"]["query"] for r in _records(pursuit)
                if r["record_type"] == "kb_retrieval"
                and r["kb"]["step"] == "card_search"]
    assert searches == EXPECTED_TOPICS  # one search per topic, verbatim, in order
    opens = [r for r in _records(pursuit)
             if r["record_type"] == "kb_retrieval"
             and r["kb"]["step"] == "targeted_open"]
    assert opens  # at least one card was opened for the summarizer
    for record in opens:
        assert record["kb"]["query"] in EXPECTED_TOPICS
