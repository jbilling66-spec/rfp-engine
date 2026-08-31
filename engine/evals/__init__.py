"""Shared eval infrastructure (P10, B40/D2).

The three P8-era harnesses (poison, injection, anonymization) stay beside
their subjects (B34(18)); this package holds only what they duplicated —
case loading, fingerprints, report writes — plus the P10 suites, runner,
and release-record writer as they land. Fingerprints derive from
prompts/cases/lexicon data, never from code, so this extraction cannot
move a recorded baseline; the standing drift locks prove it (the
committed-baseline test in tests/evals/test_poison.py and the
recorded-equality test in tests/evals/test_injection_suite.py compare
stored fingerprints against recomputed ones).
"""

from engine.evals.cases import (  # noqa: F401
    files_fingerprint,
    load_cases,
    object_fingerprint,
    write_report,
)
