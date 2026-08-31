"""Manifest obligations -> the plan's Gate-2 checklist (B16's consumer).

Deterministic token-overlap matching, pinned (B28): an obligation is
covered iff STRICTLY MORE than half its title's content tokens appear
in some single section's haystack (title + question texts / purpose),
after acronym expansion. Strictly-more-than matters: at exactly half, a
two-token obligation like "integration methodology" would ride along on
any section mentioning "methodology" — a false cover that hides exactly
what the checklist exists to show.

Uncovered obligations are honest work: status "gapped" on the checklist
plus one run-log gap line (reason needs_sme — B24's fold: human
judgment needed). A manifest row the owner adds mid-phase that nothing
covers is CORRECT behavior, not a failure; tests read the live
manifest, never a hard-coded id list.
"""

from engine.kb.manifest import Manifest
from engine.kb.rank import tokenize

# Committed expansion table: buyer/manifest shorthand -> the long form
# both sides might use. Applied to section haystacks.
ACRONYMS: dict[str, tuple[str, ...]] = {
    "ocm": ("organizational", "change", "management"),
    "pm": ("project", "management"),
    "qa": ("quality", "assurance"),
}


def _tokens(text: str) -> set[str]:
    # rank.tokenize deliberately keeps trailing periods for its corpus
    # stats; for obligation matching "methodology." must equal
    # "methodology", so sentence punctuation is stripped here.
    return {t.rstrip(".") for t in tokenize(text)}


def _haystack_tokens(texts: list[str]) -> set[str]:
    tokens = set()
    for text in texts:
        tokens.update(_tokens(text))
    for short, expansion in ACRONYMS.items():
        if short in tokens:
            tokens.update(expansion)
    return tokens


def match(manifest: Manifest, sections: list[dict],
          texts_by_section: dict[str, list[str]]) -> list[dict]:
    """-> obligations[] rows in manifest order. texts_by_section maps
    section_id -> the texts that count as its content (question texts on
    Path A; title + purpose on Path B)."""
    section_tokens = {
        s["section_id"]: _haystack_tokens(
            [s["title"]] + texts_by_section.get(s["section_id"], [])
        )
        for s in sections
    }
    out = []
    for obligation in manifest.obligations:
        content = _tokens(obligation["title"])
        covering = [
            sid for sid, tokens in section_tokens.items()
            if content and len(content & tokens) * 2 > len(content)
        ]
        row = {
            "id": obligation["id"],
            "title": obligation["title"],
            "status": "covered" if covering else "gapped",
        }
        if covering:
            row["section_ids"] = sorted(covering)
        out.append(row)
    return out


def obligation_ping(obligation: dict) -> str:
    """The 2-line gap ping for an uncovered obligation (code-composed)."""
    return (
        f"[core-content manifest / {obligation['id']}] {obligation['title']}\n"
        "No planned section covers this obligation — add a section, map "
        "it to an existing one, or confirm it is out of scope for this "
        "pursuit."
    )
