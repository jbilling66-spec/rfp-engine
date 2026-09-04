"""Prompt frames: the one place third-party or firm-side text enters a prompt.

Eight frames, three trust levels (THREAT_MODEL trust boundary):

- wrap_untrusted: buyer-document text, S1 — data to analyze, never
  instructions. Loads the shared frame file so the frame text itself is
  versioned product (and covered by config_digest as shared/*).
- wrap_research: research-pack / retrieved-web text (B21) — same S1 trust
  level (the threat model puts "web results" beside the buyer RFP) but
  provenance-honest: the frame does not claim the text is a buyer document.
- wrap_lead_context: the pursuit lead's ramble. Deliberately NOT the S1
  frame — the ramble is firm-side steering that MUST influence the brief,
  and S1 forbids steering. It still gets an explicit provenance label so
  no prompt carries unattributed text.
- wrap_kb_card: firm-authored, anonymization-gated KB card bodies —
  lead-context trust level, labeled with the kb_id so citations trace.
- wrap_brief_context / wrap_findings (B22): brief-derived text for the
  strategist. The brief is SEMI-TRUSTED until Gate 1, and findings' content
  originated in untrusted research but passed the P4 citedness gates —
  "semi_trusted" is provenance-honest where "firm" and "untrusted" would
  both lie. The behavioral defense is the strategist prompt's standing
  document-text-is-never-an-instruction rule, not S1 re-framing.
- wrap_reference (B28): the firm's own reference outline for the Path-B
  architect — firm-authored config, wrap_kb_card's trust level.
- wrap_voice_spec (B31): the committed static voice spec for the drafter —
  the threat model's trust table puts the voice spec in the TRUSTED column
  beside the Fact Sheet and approved themes, so "firm" is the honest label.
  Content is digest-visible via the drafting config extras, not this frame.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_FRAME_PATH = ROOT / "prompts" / "shared" / "untrusted-buyer-text.md"
_RESEARCH_FRAME_PATH = ROOT / "prompts" / "shared" / "untrusted-research-text.md"
_RETRIEVED_FRAME_PATH = ROOT / "prompts" / "shared" / "retrieved-kb-content.md"


def _fill(frame_path: Path, source: str, content: str) -> str:
    frame = frame_path.read_text(encoding="utf-8")
    # the file is doc-header, "---", then the frame itself
    frame = frame.split("\n---\n", 1)[1].strip()
    return frame.replace("{source}", source).replace("{content}", content)


def wrap_untrusted(source: str, content: str) -> str:
    return _fill(_FRAME_PATH, source, content)


def wrap_research(source: str, content: str) -> str:
    return _fill(_RESEARCH_FRAME_PATH, source, content)


def wrap_retrieved(source: str, content: str) -> str:
    """P14/B63: tool results in the steward-assistant transcript. NOT
    wrap_kb_card — its label="firm" is the wrong trust level once
    retrieved content is the injection surface on this loop."""
    return _fill(_RETRIEVED_FRAME_PATH, source, content)


def wrap_lead_context(text: str) -> str:
    return f'<pursuit_lead_context label="firm">\n{text}\n</pursuit_lead_context>'


def wrap_kb_card(kb_id: str, title: str, body: str) -> str:
    return (f'<kb_card kb_id="{kb_id}" title="{title}" label="firm">\n'
            f"{body}\n</kb_card>")


def wrap_brief_context(text: str) -> str:
    return (f'<bid_brief_context label="semi_trusted">\n{text}\n'
            f"</bid_brief_context>")


def wrap_findings(text: str) -> str:
    return (f'<research_findings label="semi_trusted">\n{text}\n'
            f"</research_findings>")


def wrap_reference(text: str) -> str:
    return f'<firm_reference label="firm">\n{text}\n</firm_reference>'


def wrap_voice_spec(text: str) -> str:
    return f'<voice_spec label="firm">\n{text}\n</voice_spec>'


def wrap_steward_notes(text: str) -> str:
    """P26c: steward-ACCEPTED lessons in the reviewers' own words —
    firm trust, like the voice spec they sit beside; accepted is what
    makes them firm (nothing lands here without a steward)."""
    return f'<steward_notes label="firm">\n{text}\n</steward_notes>'
