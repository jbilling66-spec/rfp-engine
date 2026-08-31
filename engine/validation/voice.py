"""Voice Polish, deterministic at P8 (B34(10)): a prohibited-word scan
over the voice spec's own enrichment table — zero model calls, never
mutates. An uncalibrated voice judge would train review fatigue before
the one control that matters has earned trust; the honest P8 check is
the list the owner approved, applied by code. Model voice judgment lands with
the Voice Miner (A2) under calibration (A4).

The table's display forms carry variants ("world-class / industry-leading")
and qualifiers ("leverage (verb)") — parsed to word-boundary patterns.
Exact-form matching by design: inflection coverage is a J3.5/P10 tuning
question, not something to guess at silently.
"""

import re

from engine.drafting.compose import VOICE_DEFAULT
from engine.validation.findings import Finding, make_finding

_ROW = re.compile(r"^\|\s*([^|]+?)\s*\|", re.MULTILINE)
# Skipped by VALUE, not by a regex lookahead: `\s*` can match empty, so a
# guard placed ahead of it backtracks and admits the very row it excludes
# — which is how the header word "Prohibited" became an enforced term
# nobody approved (found by the P10 voice eval, P10-F11).
_HEADER_CELLS = frozenset({"prohibited"})


def prohibited_terms(voice_path=VOICE_DEFAULT) -> list[str]:
    """Parse the `## Prohibited words` table's first column into scan
    terms. Tolerant of the section's absence (enrichments are optional
    config) — no section, no scan, honestly."""
    text = voice_path.read_text(encoding="utf-8")
    marker = "## Prohibited words"
    if marker not in text:
        return []
    section = text.split(marker, 1)[1].split("\n## ", 1)[0]
    terms: list[str] = []
    for match in _ROW.finditer(section):
        cell = match.group(1).strip()
        if not cell or cell.startswith("---") or cell.lower() in _HEADER_CELLS:
            continue
        for variant in cell.split("/"):
            term = re.sub(r"\s*\([^)]*\)", "", variant).strip().lower()
            if term and term not in terms:
                terms.append(term)
    return terms


def voice_findings(section_id: str, prose: str, terms: list[str]
                   ) -> list[Finding]:
    """One finding per distinct prohibited term present (word-boundary,
    case-insensitive). Advisory: polish draws eyes, never gates."""
    findings = []
    lowered = prose.lower()
    for term in terms:
        if re.search(rf"(?<!\w){re.escape(term)}(?!\w)", lowered):
            findings.append(make_finding(
                check="voice_polish", rule="prohibited_word",
                disposition="advisory",
                message=f"prohibited term {term!r} present — see the voice "
                        f"spec's use-instead column",
                section_id=section_id, slot_id=term.replace(" ", "_")))
    return findings
