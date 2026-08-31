"""Conditioning surfaces: the voice frame's single-source regex, the
voice-spec digest fold (prompts-are-product — an edit changes
config_digest), the S5 tools narrowing pinned, every trust frame present
in the built prompt, and the v1 cacheable-prefix rule (one stable system
string across every drafting call).
"""

import pytest
import yaml

from engine.drafting.compose import ROOT, VOICE_DEFAULT
from engine.llm import effective_config
from engine.llm.frames import wrap_voice_spec
from engine.runlog import config_digest
from tests.drafting.fixtures.drafts import (
    KB_CARD_RX,
    SpyCaller,
    VOICE_RX,
    drafting_extras,
    make_drafter_script,
    run_drafting_package,
)
from tests.planning.fixtures.plans import BRIEF_RX


@pytest.fixture(scope="module")
def spied(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("draft-frames")
    fake = SpyCaller(make_drafter_script())
    pursuit, report = run_drafting_package(tmp, fake=fake)
    assert report.status == "complete"
    return pursuit, fake


def test_voice_frame_matches_the_single_source_regex():
    assert VOICE_RX.search(wrap_voice_spec("BODY")).group(1) == "BODY"


def test_voice_edit_changes_config_digest(tmp_path):
    baseline = config_digest(effective_config(extra=drafting_extras()))
    variant = tmp_path / "voice-spec.md"
    variant.write_text(
        VOICE_DEFAULT.read_text(encoding="utf-8")
        + "11. **Bolder** — say it once, plainly.\n",
        encoding="utf-8")
    edited = config_digest(effective_config(extra=drafting_extras(variant)))
    assert baseline != edited


def test_drafter_config_is_narrowed_to_no_tools():
    cfg = yaml.safe_load(
        (ROOT / "prompts" / "section_drafter" / "config.yaml")
        .read_text(encoding="utf-8"))
    assert cfg == {"tier": "mid", "tools": []}  # S5 narrowing, B31(1)


def test_drafting_prompt_carries_every_trust_frame(spied):
    _, fake = spied
    draft_prompts = [c["prompt"] for c in fake.calls
                     if c["prompt"].startswith("Task: draft.")]
    assert draft_prompts
    prompt = draft_prompts[0]  # 1-delivery-approach: hits + slots present
    assert VOICE_RX.search(prompt)          # firm voice spec
    assert BRIEF_RX.search(prompt)          # planning's renderer, reused
    assert '<buyer_document source="slot:' in prompt  # S1 on question text
    assert KB_CARD_RX.search(prompt)        # opened plan selection


def test_system_prompt_is_the_stable_cacheable_prefix(spied):
    # v1 lesson: nothing per-request above the system line.
    _, fake = spied
    systems = {c["system"] for c in fake.calls}
    assert len(systems) == 1
    assert systems.pop() == (
        ROOT / "prompts" / "section_drafter" / "prompt.md"
    ).read_text(encoding="utf-8")


def test_every_drafting_call_is_mid_tier(spied):
    _, fake = spied
    assert fake.calls
    assert {c["tier"] for c in fake.calls} == {"mid"}
    assert {c["agent"] for c in fake.calls} == {"section_drafter"}
