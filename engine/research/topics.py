"""Abstract-topic derivation and the S6 query guard (B21(3)).

S6/T5: the researchers' queries must never carry deal-identifying buyer text.
The model invents no queries at all — every query IS a derived topic,
and topics come only from this committed vocabulary table, keyed on the
brief's vertical and what-is-bought text. assert_abstracted is the
belt-and-braces runtime guard: it runs before any card_search and before any
query-bearing emit, and raises loudly rather than let a leaky query reach a
log line (kb.query is logged in the clear).

The S6 line (B21(3)): deal-identifying means distinctive name tokens (buyer,
incumbent) — not service-line vocabulary. "ERP implementation" is generic;
"Northwind" is not. _GENERIC_NAME_TOKENS is the one committed list drawing
that line inside names; revisit at A6 with live queries.
"""

import re

from engine.contracts import ContractError

# (trigger substring, topic) — trigger matched case-insensitively against the
# brief's vertical + what_is_bought text. Order is emission order.
TOPIC_VOCAB = (
    ("healthcare", "regional health system strategic priorities"),
    ("healthcare", "health system back-office modernization trends"),
    ("erp", "ERP implementation delivery approaches"),
    ("erp", "ERP program vendor landscape and incumbent dynamics"),
    ("implementation", "implementation services procurement and budgeting practices"),
)

FALLBACK_TOPIC = "buyer background and procurement context"

_MAX_TOPICS = 5

# Generic words that appear inside organization names but identify no one.
# Only distinctive remainder tokens (len >= 4) become forbidden.
_GENERIC_NAME_TOKENS = frozenset({
    "regional", "national", "health", "system", "systems", "hospital",
    "medical", "center", "centre", "consulting", "consultants", "group",
    "services", "solutions", "partners", "associates", "company",
    "corporation", "incorporated", "the", "and",
})


def derive_topics(brief: dict) -> list[str]:
    text = " ".join([
        brief.get("buyer", {}).get("vertical") or "",
        brief.get("procurement", {}).get("what_is_bought") or "",
    ]).lower()
    topics: list[str] = []
    for trigger, topic in TOPIC_VOCAB:
        if trigger in text and topic not in topics:
            topics.append(topic)
    return topics[:_MAX_TOPICS] or [FALLBACK_TOPIC]


def forbidden_tokens(brief: dict) -> list[str]:
    buyer = brief.get("buyer", {})
    names = [buyer.get("name") or "", buyer.get("incumbent") or ""]
    forbidden: list[str] = []
    for name in names:
        if not name.strip():
            continue
        forbidden.append(name.strip().lower())
        for token in re.findall(r"[a-z0-9]+", name.lower()):
            if len(token) >= 4 and token not in _GENERIC_NAME_TOKENS:
                forbidden.append(token)
    seen: set[str] = set()
    return [t for t in forbidden if not (t in seen or seen.add(t))]


def assert_abstracted(query: str, forbidden: list[str]) -> None:
    lowered = query.lower()
    for item in forbidden:
        if re.search(rf"\b{re.escape(item)}\b", lowered):
            raise ContractError(
                f"S6 violation: query {query!r} carries buyer-identifying text {item!r}")
