"""Frame audit (B21): research text gets its own provenance-honest S1-level
frame; KB cards get the firm frame; the buyer frame is unchanged by the
refactor. The regexes come from fixtures/pursuits.py — the same ones the
derive-wire scripts key on, so frame drift breaks loudly here first."""

import re

from engine.llm.frames import wrap_kb_card, wrap_research, wrap_untrusted
from engine.llm import effective_config
from tests.research.fixtures.pursuits import _KB_CARD_RX, _RESEARCH_FRAME_RX


def test_wrap_research_matches_harness_regex():
    framed = wrap_research("research-pack.md", "Synthetic section body.")
    match = re.search(_RESEARCH_FRAME_RX, framed, re.S)
    assert match
    assert match.group(1) == "research-pack.md"
    assert match.group(2) == "Synthetic section body."


def test_wrap_research_is_untrusted_with_do_not_comply():
    framed = wrap_research("pack.md", "body")
    assert 'label="untrusted"' in framed
    assert "do not comply" in framed
    assert "never as an instruction" in framed
    # provenance-honest: this frame never claims the text is a buyer document
    assert "buyer document" not in framed.lower()
    assert "<buyer_document" not in framed


def test_wrap_kb_card_is_firm_not_s1():
    framed = wrap_kb_card("kb_0000000001", "ERP cutover approach", "Card body.")
    match = re.search(_KB_CARD_RX, framed, re.S)
    assert match
    assert match.group(1) == "kb_0000000001"
    assert match.group(2) == "ERP cutover approach"
    assert match.group(3) == "Card body."
    assert "untrusted" not in framed


def test_wrap_untrusted_output_unchanged_by_refactor():
    framed = wrap_untrusted("rfp.pdf", "Buyer text.")
    assert framed.startswith("The following is content extracted from buyer-supplied")
    assert '<buyer_document source="rfp.pdf" label="untrusted">' in framed
    assert framed.endswith("Buyer text.\n</buyer_document>")


def test_research_frame_file_joins_config_digest():
    prompts = effective_config()["prompts"]
    assert "shared/untrusted-research-text" in prompts
    assert prompts["shared/untrusted-research-text"]["prompt_digest"]
