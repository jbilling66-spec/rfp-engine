"""Anonymization: typed placeholders at ingestion (K5), scan as the gate.

Substitution replaces normalized occurrences of each indexed identifier.
The scan is deliberately STRICTER than substitution: it also matches
possessives, whitespace-wrapped forms, the distinctive tokens of multi-word
names, their acronyms, and restated fee forms ($1,975,000 → 1975000,
$1.975M, $2.0M, $1,975K). Any post-substitution hit blocks the write. That
asymmetry is what makes recall == 1.00 (E4) enforcement code, not model
trust — the model proposes the identifier list, but a residue the model
missed a variant of still trips the gate.

P28 (P1-4): the identifier universe is no longer the model's list alone.
`detect_structured` names the classes a regex can find — contact details,
URLs and domains, street addresses, tax-id shapes, reference numbers — so
they are SUBSTITUTED before any model is trusted, and the scan runs the same
detectors unconditionally afterwards as the backstop. Text is normalized
(NFC, invisible characters stripped) on both sides of every match, so a
name split by a soft hyphen or written in decomposed Unicode neither
escapes substitution nor hides from the scan.

The result is a boolean, never a rate (R13): one leaked identifier is an
incident on the named-human path, not a trend point.
"""

import re
import unicodedata
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable

PLACEHOLDER_TYPES = {
    "CLIENT": "[CLIENT]",
    "FEE": "[FEE]",
    "REFERENCE_NAME": "[REFERENCE_NAME]",
    # P28 (P1-4; the owner's call at planning, 2026-09-05): the taxonomy
    # is the domain's — accounting/consulting proposal material.
    "ORGANIZATION": "[ORGANIZATION]",  # a third party that is not the client
    "CONTACT": "[CONTACT]",  # an email address or phone number
    "URL": "[URL]",  # a web address or bare domain
    "ADDRESS": "[ADDRESS]",  # a street address
    "TAX_ID": "[TAX_ID]",  # an EIN- or SSN-shaped number
    "REFERENCE_NUMBER": "[REFERENCE_NUMBER]",  # contract / PO / RFP / invoice
    # Fallback bucket for a wire type outside the taxonomy. TODO(spec-gap):
    # the classes above are the domain's as of P28 (B121 §1a); A1's
    # real-material review may ADD a class — that review is the closer,
    # and the register (review §5.16 onward) records which class arrived
    # and why. A type the wire names that this table lacks is cleared and
    # reported by the wire parser, never silently dropped.
    "REDACTED": "[REDACTED]",
}

# The classes code detects without an index entry (P28). The scan names a
# residue of each with a bracketed label rather than an identifier value.
STRUCTURED_TYPES = ("CONTACT", "URL", "ADDRESS", "TAX_ID", "REFERENCE_NUMBER")
_STRUCTURED_LABEL = {
    "CONTACT": "<contact_info>",  # the pre-P28 name, pinned by test
    "URL": "<url>",
    "ADDRESS": "<address>",
    "TAX_ID": "<tax_id>",
    "REFERENCE_NUMBER": "<reference_number>",
}

# Tokens too generic to indicate a specific client on their own. Kept small
# on purpose: a false positive trains reviewers to ignore the finding (v1),
# but the safe failure direction here is still to block.
_GENERIC_TOKENS = frozenset(
    "health medical center partners group county valley regional municipal "
    "utilities schools insurance hospital system systems services city "
    "community district national university college "
    # P28: the words a third-party ORGANIZATION name is built from — a
    # subcontractor called "<Name> Data Systems" must flag on <Name>, never
    # on "data" in every card that mentions data.
    "data solutions technologies technology consulting consultants "
    "associates advisors advisory corporation company incorporated limited "
    "international global software digital analytics management "
    "engineering "
    # "client" is here because a client name containing the word (or the
    # [CLIENT] placeholder itself) would otherwise flag every ordinary use
    # of "client" in every card — the exact false-positive class that
    # trains reviewers to ignore findings. The multi-word exact pattern
    # still matches such a name in full.
    "client".split()
)

# The characters a PDF extraction or a copy-paste plants inside a name:
# soft hyphen, zero-width space/joiners, word joiner, byte-order mark.
_INVISIBLE = re.compile("[\u00ad\u200b\u200c\u200d\u2060\ufeff]")


# P29a (P2-52): the Latin typographic ligatures a PDF render pastes for
# "fi"/"fl"/"ff"/"ffi"/"ffl"/"st" (U+FB00–U+FB06). Folded explicitly —
# NFKC would fold them too, but it also rewrites non-breaking spaces,
# trademark signs, fractions and full-width forms, and apply_placeholders
# RETURNS the normalized text, so NFKC would move the stored bytes (and
# content hashes) of every card.
_LIGATURES = str.maketrans({
    "\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi",
    "\ufb04": "ffl", "\ufb05": "st", "\ufb06": "st"})


def normalize_text(text: str) -> str:
    """NFC plus the invisible characters removed and the typographic
    ligatures folded — lossless for prose, and applied to BOTH sides of
    every match (P28, P29a): an identifier written in decomposed Unicode,
    split by a soft hyphen, or spelled with a ligature still matches."""
    return (_INVISIBLE.sub("", unicodedata.normalize("NFC", text))
            .translate(_LIGATURES))


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
    parts = [re.escape(p) for p in normalize_text(identifier).split()]
    return re.compile(_whole(r"\s+".join(parts)), re.IGNORECASE)


def apply_placeholders(text: str, identifiers: dict[str, str]) -> str:
    """identifiers: original string -> placeholder type. Longest-first so a
    full name is replaced before any shorter identifier embedded in it.
    The returned text is normalized (P28) — the invisible characters that
    could split a match are gone from what persists."""
    text = normalize_text(text)
    for original in sorted(identifiers, key=len, reverse=True):
        if not original.strip():
            continue  # an empty key would match everywhere
        token = PLACEHOLDER_TYPES.get(
            identifiers[original], PLACEHOLDER_TYPES["REDACTED"]
        )
        text = _identifier_regex(original).sub(token, text)
    return text


def merge_identifiers(*layers: dict[str, str]) -> dict[str, str]:
    """The identifier index from its sources, LATER layers taking
    precedence — except that the fallback never downgrades a typed entry
    (P28, B121 §5): known > typed > REDACTED. Values are normalized so two
    spellings of one identifier collapse to one entry."""
    merged: dict[str, str] = {}
    for layer in layers:
        for value, itype in (layer or {}).items():
            key = normalize_text(str(value)).strip()
            if not key:
                continue
            if itype == "REDACTED" and merged.get(key, "REDACTED") != "REDACTED":
                continue
            merged[key] = itype
    return merged


_WORD = r"[^\W\d_][^\W\d_'’-]*"  # a Unicode-letter token (Renée, O'Neil)


def _distinctive_tokens(identifier: str) -> list[str]:
    tokens = re.findall(_WORD, normalize_text(identifier))
    return [
        t for t in tokens if len(t) >= 4 and t.lower() not in _GENERIC_TOKENS
    ]


_ACRONYM_STOP = frozenset("the and for of de del la le von van".split())


def _acronym_variants(identifier: str) -> list[str]:
    """The initials of a multi-word name (P28): "Cascade Valley Medical
    Center" → CVMC, dotted or not, case-sensitive. Two-letter initials
    are not generated — the collision cost outweighs the catch."""
    words = [w for w in re.findall(r"[^\W\d_]+", normalize_text(identifier))
             if w.lower() not in _ACRONYM_STOP]
    if len(words) < 3:
        return []
    initials = "".join(w[0].upper() for w in words)
    return [initials, ".".join(initials) + "."]


def _fee_variants(identifier: str) -> list[str]:
    """Restated forms of a dollar figure: separators stripped, $ dropped,
    thousands ($1,975K / 1975K), short-scale millions at full, one- and
    two-decimal precision ($1,975,000 → $1.975M / $2M / $1.98M, 1.975
    million, $1.975MM). A rounding that collides with a neighbouring figure
    is a block a human clears — cheaper than a leaked restatement (T2)."""
    if not re.fullmatch(r"\$?[\d,]+(?:\.\d+)?", identifier.strip()):
        return []
    bare = identifier.strip().lstrip("$")
    digits = bare.replace(",", "")
    variants = [digits]
    if bare != digits:
        variants.append(bare)  # the comma form without its $ escapes exact match
    if "." in digits:
        # P29a (P2-51): a cents form is the likely INDEXED spelling — the
        # readers copy fee tables verbatim — while the cover letter drops
        # the cents and the summary rounds. The integer family derives
        # from the whole-dollar part either way.
        whole, _, _cents = digits.partition(".")
        if not whole.isdigit():
            return variants
        variants += [whole, f"{int(whole):,}"]
        digits = whole
    value = int(digits)
    if value >= 1_000 and value % 1_000 == 0:
        thousands = value // 1_000
        variants += [f"${thousands:,}K", f"{thousands:,}K",
                     f"${thousands}K", f"{thousands}K"]
    if len(digits) >= 7:
        exact = Decimal(value) / Decimal(1_000_000)
        forms = {format(exact.normalize(), "f")}
        for places in ("0.1", "0.01"):
            rounded = exact.quantize(Decimal(places), rounding=ROUND_HALF_UP)
            forms.add(format(rounded.normalize(), "f"))
        for millions in sorted(forms):
            variants += [f"${millions}M", f"{millions}M",
                         f"{millions} million",
                         f"${millions}MM", f"{millions}MM"]
    return variants


def _scan_patterns(identifier: str) -> list[re.Pattern]:
    patterns = [_identifier_regex(identifier)]
    if detect_structured(identifier):
        # A structured identifier (an email, a URL, an address, a number)
        # is matched whole: its tokens ("portal", "login") are ordinary
        # words, and the structured detectors below already catch any
        # restated form of the value itself.
        return patterns
    for token in _distinctive_tokens(identifier):
        patterns.append(re.compile(_whole(re.escape(token)), re.IGNORECASE))
    for acronym in _acronym_variants(identifier):
        patterns.append(re.compile(
            rf"(?<![A-Za-z]){re.escape(acronym)}(?![A-Za-z])"))
    for variant in _fee_variants(identifier):
        patterns.append(re.compile(_whole(re.escape(variant)), re.IGNORECASE))
    return patterns


# Structured identifiers are identifying regardless of whether anything
# indexed them (v1's naming guard, widened at P28). Every pattern REQUIRES
# its separators on purpose: metrics like 3,800 or 0.35, ISO dates,
# "SOC 2 Type II", "ISO 27001", "Form 990", "ASC 842", "FY2025", "10-K" never
# match — a false positive here would train reviewers to ignore the finding.
_TLDS = "com|org|net|gov|edu|io|co|us|example"
_STREET_TYPES = ("Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Drive|Dr|Lane|Ln"
                 "|Way|Court|Ct|Parkway|Pkwy|Plaza|Place|Pl|Highway|Hwy")
_STRUCTURED_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("CONTACT", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    ("CONTACT", re.compile(
        r"(?<![\d-])(?:\+1[ .-])?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?![\d-])")),
    ("URL", re.compile(r"https?://[^\s<>\"')\]]+", re.IGNORECASE)),
    ("URL", re.compile(
        rf"(?<![\w@.-])(?:[a-z0-9-]+\.)+(?:{_TLDS})(?![\w-])", re.IGNORECASE)),
    ("TAX_ID", re.compile(r"(?<![\d-])\d{2}-\d{7}(?![\d-])")),
    ("TAX_ID", re.compile(r"(?<![\d-])\d{3}-\d{2}-\d{4}(?![\d-])")),
    ("ADDRESS", re.compile(
        rf"(?<!\w)\d{{1,6}}\s+(?:[A-Z][\w'.-]*\s+){{1,4}}(?:{_STREET_TYPES})\.?"
        r"(?:,?\s+(?:Suite|Ste|Unit|Floor|Fl)\.?\s*[\w-]+)?(?!\w)")),
    ("REFERENCE_NUMBER", re.compile(
        r"\b(?:P\.?O\.?|Purchase Order|Contract|Engagement|Agreement|RFP|RFQ"
        r"|RFI|Solicitation|Bid|Invoice)\s*(?:No\.?|Number|#|ID)?\s*:?\s*"
        r"(?=[A-Z0-9./-]*\d)[A-Z0-9][A-Z0-9./-]{3,}(?![\w./-])")),
]


def detect_structured(text: str) -> dict[str, str]:
    """value -> type for every structured identifier in `text` (P28):
    emails and phones (CONTACT), web addresses and bare domains (URL),
    EIN/SSN shapes (TAX_ID), street addresses (ADDRESS) and contract / PO /
    RFP / invoice numbers (REFERENCE_NUMBER). Model-independent: the
    ingest index takes these BEFORE any model's list, so they are
    substituted, and the scan runs them unconditionally afterwards."""
    found: dict[str, str] = {}
    normalized = normalize_text(text)
    for itype, pattern in _STRUCTURED_PATTERNS:
        for match in pattern.finditer(normalized):
            value = match.group(0).rstrip(".,;:")
            if value and value not in found:
                found[value] = itype
    return found


def cleaners(identifiers: dict[str, str]):
    """P28/P29a (P1-46, P1-49): the pair every door that persists human
    or buyer text uses — `clean` substitutes the known identifiers AND
    the structured classes code detects in the text itself (an email is
    placeholdered even when no buyer name is known); `verify` is the
    ingestion scanner over the cleaned strings, the same gate a firm
    document passes. One home: the accept-time learn route, the gap→card
    spawner and the write-back route all build from here."""
    def clean(text: str) -> str:
        return apply_placeholders(
            text, merge_identifiers(detect_structured(text), identifiers))

    def verify(texts: dict[str, str]) -> list:
        return scan(texts, identifiers)

    return clean, verify


def scan(texts: dict[str, str], identifiers: Iterable[str]) -> list[Finding]:
    """texts: location label -> retrievable text (bodies, titles, summaries).
    Returns every identifier residue found, with where and what matched.
    Structured identifiers — contact details, URLs, addresses, tax ids,
    reference numbers — are flagged unconditionally: they identify someone
    whether or not the identifier index knew about them."""
    findings = []
    normalized = {location: normalize_text(text)
                  for location, text in sorted(texts.items())}
    for identifier in sorted(set(identifiers)):
        patterns = _scan_patterns(identifier)
        for location, text in normalized.items():
            for pattern in patterns:
                match = pattern.search(text)
                if match:
                    findings.append(
                        Finding(location=location, identifier=identifier,
                                matched=match.group(0))
                    )
                    break
    for location, text in normalized.items():
        for value, itype in detect_structured(text).items():
            findings.append(
                Finding(location=location, identifier=_STRUCTURED_LABEL[itype],
                        matched=value)
            )
    return findings


def scan_passed(findings: list[Finding]) -> bool:
    """Boolean, never a percentage (R13)."""
    return not findings
