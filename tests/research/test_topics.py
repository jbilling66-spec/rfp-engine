"""Topic derivation is deterministic committed vocabulary (B21(3)); the S6
guard raises on deal-identifying text and passes service-line vocabulary —
the line B21 draws. Unit-level brief dicts here mirror the pdf twin's fields;
the run-level golden pins against the real pipeline in test_airgapped."""

import pytest

from engine.contracts import ContractError
from engine.research import (
    FALLBACK_TOPIC,
    TOPIC_VOCAB,
    assert_abstracted,
    derive_topics,
    forbidden_tokens,
)

_BRIEF = {
    "buyer": {"name": "Northwind Regional Health", "vertical": "healthcare",
              "incumbent": "Summit Apex Consulting"},
    "procurement": {"what_is_bought": "ERP implementation services"},
}


def test_derivation_is_deterministic_and_bounded():
    first = derive_topics(_BRIEF)
    assert first == derive_topics(_BRIEF)
    assert 1 <= len(first) <= 5
    assert len(first) == len(set(first))
    vocab_topics = {topic for _, topic in TOPIC_VOCAB} | {FALLBACK_TOPIC}
    assert set(first) <= vocab_topics


def test_pdf_shaped_brief_golden_topics():
    assert derive_topics(_BRIEF) == [
        "regional health system strategic priorities",
        "health system back-office modernization trends",
        "ERP implementation delivery approaches",
        "ERP program vendor landscape and incumbent dynamics",
        "implementation services procurement and budgeting practices",
    ]


def test_empty_brief_falls_back_never_empty():
    assert derive_topics({}) == [FALLBACK_TOPIC]
    assert derive_topics({"buyer": {"vertical": "forestry"},
                          "procurement": {"what_is_bought": "timber cruise"}}) == [
        FALLBACK_TOPIC]


def test_forbidden_tokens_are_distinctive_only():
    forbidden = forbidden_tokens(_BRIEF)
    assert "northwind regional health" in forbidden
    assert "northwind" in forbidden
    assert "summit apex consulting" in forbidden
    assert "summit" in forbidden
    assert "apex" in forbidden
    # generic name words never become forbidden — they are not deal-identifying
    for generic in ("regional", "health", "consulting"):
        assert generic not in forbidden


def test_guard_raises_on_buyer_identifying_query():
    forbidden = forbidden_tokens(_BRIEF)
    with pytest.raises(ContractError, match="S6 violation"):
        assert_abstracted("Northwind ERP timeline", forbidden)
    with pytest.raises(ContractError, match="S6 violation"):
        assert_abstracted("summit apex consulting engagement history", forbidden)


def test_guard_passes_service_line_vocabulary():
    forbidden = forbidden_tokens(_BRIEF)
    assert_abstracted("ERP implementation delivery approaches", forbidden)
    assert_abstracted("regional health system strategic priorities", forbidden)


def test_every_derived_topic_passes_the_guard():
    forbidden = forbidden_tokens(_BRIEF)
    for topic in derive_topics(_BRIEF):
        assert_abstracted(topic, forbidden)
