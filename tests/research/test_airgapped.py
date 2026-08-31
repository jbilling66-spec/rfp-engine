"""Acceptance core (ROADMAP P4): the airgapped run completes with the
synthetic pack, both researchers' findings are cited into the brief, and the
P3 brief contract is untouched underneath the two added fields."""

import pytest

from engine.contracts import validate
from engine.runlog import read_run
from tests.intake.fixtures.packages import RAMBLE, run_package
from tests.research.fixtures.pursuits import (
    EXPECTED_TOPICS,
    PACK_SECTIONS,
    run_research_package,
)


@pytest.fixture(scope="module")
def airgapped(tmp_path_factory):
    return run_research_package(tmp_path_factory.mktemp("airgapped"))


def _records(pursuit):
    return read_run(pursuit.root / "runs" / "run_0002" / "run.jsonl")


def test_airgapped_run_completes(airgapped):
    pursuit, report = airgapped
    assert report.status == "complete"
    assert report.brief_path is not None and report.brief_path.exists()
    records = _records(pursuit)
    assert records[-1]["record_type"] == "run_end"
    assert records[-1]["run"]["status"] == "completed"


def test_topics_match_golden(airgapped):
    _, report = airgapped
    assert report.topics == EXPECTED_TOPICS


def test_findings_are_cited_into_the_brief(airgapped):
    pursuit, _ = airgapped
    buyer = pursuit.read_artifact("brief.json")["buyer"]
    findings = buyer["research_findings"]
    assert findings
    for finding in findings:
        assert finding["claim"]
        assert finding["source_kind"] in ("internal_kb", "research_pack")
        assert finding["source"]
        assert finding["topic"]
    pack_urls = {url for url, _ in PACK_SECTIONS.values()}
    pack_findings = [f for f in findings if f["source_kind"] == "research_pack"]
    assert {f["source"] for f in pack_findings} == pack_urls  # WP3: source URLs
    for _, marker in PACK_SECTIONS.values():
        assert any(marker in f["claim"] for f in pack_findings)


def test_internal_findings_cite_only_opened_cards(airgapped):
    pursuit, _ = airgapped
    findings = pursuit.read_artifact("brief.json")["buyer"]["research_findings"]
    internal = [f for f in findings if f["source_kind"] == "internal_kb"]
    assert internal  # the topic vocabulary reaches the ERP corpus
    opened = {
        kb_id
        for r in _records(pursuit) if r["record_type"] == "kb_retrieval"
        for kb_id in r["kb"]["cards_opened"]
    }
    assert {f["source"] for f in internal} <= opened


def test_research_mode_used_is_airgapped(airgapped):
    pursuit, _ = airgapped
    assert pursuit.read_artifact("brief.json")["buyer"]["research_mode_used"] == "airgapped"
    header = _records(pursuit)[0]
    assert header["record_type"] == "run_start"
    assert header["run"]["research_mode"] == "airgapped"


def test_brief_revalidates_and_p3_fields_untouched(airgapped, tmp_path):
    pursuit, _ = airgapped
    brief = pursuit.read_artifact("brief.json")
    validate("bid_brief", brief)
    reference_pursuit, _ = run_package(tmp_path, "pdf", ramble=RAMBLE)
    reference = reference_pursuit.read_artifact("brief.json")
    stripped = {**brief, "buyer": {k: v for k, v in brief["buyer"].items()
                                   if k not in ("research_findings",
                                                "research_mode_used")}}
    assert stripped == reference


def test_every_claimed_field_has_a_writer(airgapped):
    # B11 class: a field the phase claims must be non-trivially written
    pursuit, _ = airgapped
    buyer = pursuit.read_artifact("brief.json")["buyer"]
    assert buyer["research_mode_used"]
    findings = buyer["research_findings"]
    assert findings
    for key in ("claim", "topic", "source_kind", "source"):
        assert all(f.get(key) for f in findings)
    assert any(f.get("detail") for f in findings)
    assert {f["source_kind"] for f in findings} == {"internal_kb", "research_pack"}
