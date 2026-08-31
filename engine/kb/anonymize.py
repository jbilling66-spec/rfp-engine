"""Anonymization: typed placeholders at ingestion (K5), scan as the gate.

Substitution replaces normalized occurrences of each indexed identifier.
The scan is deliberately STRICTER than substitution: it also matches
possessives, whitespace-wrapped forms, the distinctive tokens of multi-word
names, and restated fee forms ($1,975,000 → 1975000, $1.975M). Any
post-substitution hit blocks the write. That asymmetry is what makes
recall == 1.00 (E4) enforcement code, not model trust — the model proposes
the identifier list, but a residue the model missed a variant of still
trips the gate.

The result is a boolean, never a rate (R13): one leaked identifier is an
incident on the named-human path, not a trend point.
"""

import re
from dataclasses import dataclass
from typing import Iterable

PLACEHOLDER_TYPES = {
    "CLIENT": "[CLIENT]",
    "FEE": "[FEE]",
    "REFERENCE_NAME": "[REFERENCE_NAME]",
    # Fallback bucket for wire identifier types outside the spec's three —
    # the taxonomy beyond CLIENT/FEE/REFERENCE_NAME is TODO(spec-gap): expanded
    # at A1, where real material shows which identifier types exist (B30(c)).
    "REDACTED": "[REDACTED]",
}

# Tokens too generic to indicate a specific client on their own. Kept small
# on purpose: a false positive trains reviewers to ignore the finding (v1),
# but the safe failure direction here is still to block.
_GENERIC_TOKENS = frozenset(
    "health medical center partners group county valley regional municipal "
    "utilities schools insurance hospital system systems services city "
    "community district national university college "
    # "client" is here because a client name containing the word (or the
    # [CLIENT] placeholder itself) would otherwise flag every ordinary use
    # of "client" in every card — the exact false-positive class that
    # trains reviewers to ignore findings. The multi-word exact pattern
    # still matches such a name in full.
    "client".split()
)


@dataclass
class Finding:
    location: str
    identifier: str
    matched: str


def _whole(pattern: str) -> str:
    return rf"(?<!\w){pattern}(?!\w)"


def _identifier_regex(identifier: str) -> re.Pattern:
    """Word-bounded, case-insensitive; internal whitespace matches any run
    of whitespace, so a name wrapped across a line still matches."""
    parts = [re.escape(p) for p in identifier.split()]
    return re.compile(_whole(r"\s+".join(parts)), re.IGNORECASE)


def apply_placeholders(text: str, identifiers: dict[str, str]) -> str:
    """identifiers: original string -> placeholder type. Longest-first so a
    full name is replaced before any shorter identifier embedded in it."""
    for original in sorted(identifiers, key=len, reverse=True):
        token = PLACEHOLDER_TYPES.get(
            identifiers[original], PLACEHOLDER_TYPES["REDACTED"]
        )
        text = _identifier_regex(original).sub(token, text)
    return text


def _distinctive_tokens(identifier: str) -> list[str]:
    tokens = re.findall(r"[A-Za-z][A-Za-z'-]*", identifier)
    return [
        t for t in tokens if len(t) >= 4 and t.lower() not in _GENERIC_TOKENS
    ]


def _fee_variants(identifier: str) -> list[str]:
    """Restated forms of a dollar figure: separators stripped, $ dropped,
    short-scale millions ($1,975,000 → $1.975M / 1.975 million)."""
    if not re.fullmatch(r"\$?[\d,]+(?:\.\d+)?", identifier.strip()):
        return []
    bare = identifier.strip().lstrip("$")
    digits = bare.replace(",", "")
    variants = [digits]
    if bare != digits:
        variants.append(bare)  # the comma form without its $ escapes exact match
    if "." not in digits and len(digits) >= 7:
        millions = f"{int(digits) / 1_000_000:g}"
        variants += [f"${millions}M", f"{millions}M", f"{millions} million"]
    return variants


def _scan_patterns(identifier: str) -> list[re.Pattern]:
    patterns = [_identifier_regex(identifier)]
    for token in _distinctive_tokens(identifier):
        patterns.append(re.compile(_whole(re.escape(token)), re.IGNORECASE))
    for variant in _fee_variants(identifier):
        patterns.append(re.compile(_whole(re.escape(variant)), re.IGNORECASE))
    return patterns


# Contact info is identifying regardless of whether anything indexed it
# (v1's naming guard). The phone pattern REQUIRES separators on purpose:
# metrics like 3,800 or 0.35 and ISO dates never match — a false positive
# here would train reviewers to ignore the finding.
_CONTACT_PATTERNS = [
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]*\w"),
    re.compile(r"(?<!\d)\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?!\d)"),
]


def scan(texts: dict[str, str], identifiers: Iterable[str]) -> list[Finding]:
    """texts: location label -> retrievable text (bodies, titles, summaries).
    Returns every identifier residue found, with where and what matched.
    Emails and phone numbers are flagged unconditionally — they identify
    someone whether or not the identifier index knew about them."""
    findings = []
    for identifier in sorted(set(identifiers)):
        patterns = _scan_patterns(identifier)
        for location, text in sorted(texts.items()):
            for pattern in patterns:
                match = pattern.search(text)
                if match:
                    findings.append(
                        Finding(location=location, identifier=identifier,
                                matched=match.group(0))
                    )
                    break
    for location, text in sorted(texts.items()):
        for pattern in _CONTACT_PATTERNS:
            match = pattern.search(text)
            if match:
                findings.append(
                    Finding(location=location, identifier="<contact_info>",
                            matched=match.group(0))
                )
    return findings


def scan_passed(findings: list[Finding]) -> bool:
    """Boolean, never a percentage (R13)."""
    return not findings
