"""Mode switch is config-only (ROADMAP P4, B3/B21): the one committed switch is
config/research.yaml, loaded inside effective_config so it is digest-visible.
Flipping the file changes config_digest; nothing else in the codebase needs an
edit. Loader failures are loud — a typo'd mode fails the run. The run cases
prove B3's smoke obligation: full_web/allowlist complete via FakeCaller with
the same output schema, and both researchers run in every mode (R1)."""

import pytest

from engine.contracts import validate
from engine.llm import RESEARCH_MODES, effective_config, research_config
from engine.llm.config import RESEARCH_YAML
from engine.runlog import config_digest, read_run
from tests.research.fixtures.pursuits import run_research_package


def _mode_yaml(tmp_path, mode: str):
    path = tmp_path / f"research-{mode}.yaml"
    path.write_text(f"research_mode: {mode}\n", encoding="utf-8")
    return path


def test_committed_default_is_airgapped():
    assert research_config(RESEARCH_YAML) == {"research_mode": "airgapped"}


def test_effective_config_carries_the_file_value(tmp_path):
    cfg = effective_config(research_yaml=_mode_yaml(tmp_path, "allowlist"))
    assert cfg["research_mode"] == "allowlist"


def test_flipping_the_file_changes_config_digest(tmp_path):
    digests = {
        mode: config_digest(effective_config(research_yaml=_mode_yaml(tmp_path, mode)))
        for mode in RESEARCH_MODES
    }
    assert len(set(digests.values())) == len(RESEARCH_MODES)


def test_loader_rejects_out_of_vocab_mode(tmp_path):
    with pytest.raises(ValueError, match="research_mode must be one of"):
        research_config(_mode_yaml(tmp_path, "offline"))


def test_loader_rejects_unknown_keys(tmp_path):
    path = tmp_path / "research.yaml"
    path.write_text("research_mode: airgapped\nweb_budget: 10\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unknown keys"):
        research_config(path)


def test_loader_rejects_non_mapping(tmp_path):
    path = tmp_path / "research.yaml"
    path.write_text("- airgapped\n", encoding="utf-8")
    with pytest.raises(ValueError, match="expected a mapping"):
        research_config(path)


# ------------------------------------------------------------- run cases


def _records(pursuit):
    return read_run(pursuit.root / "runs" / "run_0002" / "run.jsonl")


@pytest.mark.parametrize("mode", ["full_web", "allowlist"])
def test_smoke_modes_complete_with_same_output_schema(tmp_path, mode):
    pursuit, report = run_research_package(
        tmp_path, research_yaml=_mode_yaml(tmp_path, mode), pack=False)
    assert report.status == "complete"
    brief = pursuit.read_artifact("brief.json")
    validate("bid_brief", brief)
    assert brief["buyer"]["research_mode_used"] == mode
    assert _records(pursuit)[0]["run"]["research_mode"] == mode
    findings = brief["buyer"]["research_findings"]
    web = [f for f in findings if f["source_kind"] == "web"]
    assert web  # the external side produced findings in smoke mode too
    for finding in findings:  # R2: one shape in every mode
        assert finding["claim"] and finding["topic"] and finding["source"]
        assert finding["source_kind"] in ("internal_kb", "web")


@pytest.mark.parametrize("mode", ["airgapped", "full_web", "allowlist"])
def test_both_researchers_always_run(tmp_path, mode):
    pursuit, _ = run_research_package(
        tmp_path, research_yaml=_mode_yaml(tmp_path, mode),
        pack=(mode == "airgapped"))
    calls = [r for r in _records(pursuit) if r["record_type"] == "agent_call"]
    assert [c["agent"] for c in calls] == ["internal_researcher",
                                           "external_researcher"]
    assert all(c["model_tier"] == "mid" for c in calls)


def test_airgapped_without_pack_still_runs_both_and_gaps(tmp_path):
    pursuit, report = run_research_package(tmp_path, pack=False)
    assert report.status == "complete"
    records = _records(pursuit)
    calls = [r for r in records if r["record_type"] == "agent_call"]
    assert len(calls) == 2  # R1 literal: the external call still happened
    gaps = [r["gap"] for r in records if r["record_type"] == "gap"]
    assert len(gaps) == 1
    assert gaps[0]["gap_id"] == "gap_pur_pdf_research_01"
    assert gaps[0]["reason"] == "needs_sme"
    assert "research pack" in gaps[0]["question_to_human"]
    findings = pursuit.read_artifact("brief.json")["buyer"]["research_findings"]
    assert findings  # internal findings still land
    assert all(f["source_kind"] == "internal_kb" for f in findings)
