"""S6/T5 acceptance: no logged query — no string anywhere in the research
run's log — carries deal-identifying buyer text. The sweep is whole-log with
zero carve-outs (every string value in every record), and it is proven
non-vacuous first: each planted token really does appear in the buyer-facing
inputs the research stage worked from."""

import pytest

from engine.intake import extract
from engine.runlog import read_run
from tests.intake.fixtures.packages import FIXTURES, RAMBLE
from tests.research.fixtures.pursuits import (
    PACK_PATH,
    PLANTED_BUYER_TOKENS,
    run_research_package,
)


@pytest.fixture(scope="module")
def airgapped(tmp_path_factory):
    return run_research_package(tmp_path_factory.mktemp("hygiene"))


def _strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for key, value in obj.items():
            yield key
            yield from _strings(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _strings(value)


def test_planted_tokens_really_are_in_the_buyer_inputs():
    # non-vacuous: a sweep for tokens that were never present proves nothing
    inputs = extract(FIXTURES / "pdf-twin.pdf").text + "\n" + RAMBLE
    for token in PLANTED_BUYER_TOKENS:
        assert token.lower() in inputs.lower()


def test_no_research_log_string_carries_buyer_text(airgapped):
    pursuit, _ = airgapped
    records = read_run(pursuit.root / "runs" / "run_0002" / "run.jsonl")
    haystack = "\n".join(s for record in records for s in _strings(record)).lower()
    for token in PLANTED_BUYER_TOKENS:
        assert token.lower() not in haystack


def test_pack_fixture_itself_is_buyer_anonymous():
    # the strict whole-log sweep only works if the pack never names the buyer
    pack_text = PACK_PATH.read_text(encoding="utf-8").lower()
    for token in PLANTED_BUYER_TOKENS:
        assert token.lower() not in pack_text
