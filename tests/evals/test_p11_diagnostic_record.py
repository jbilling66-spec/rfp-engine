"""The P11 frozen-row clause "one live diagnostic run", carried by the
COMMITTED artifacts rather than by a fixture.

A phase whose acceptance says a live run happened must be able to prove
it from what is in the repo. These assertions read `docs/milestones/
p11-diagnostic/` directly, so they fail if the record is absent, doctored,
or does not describe the baselines it is supposed to have produced. The
precedent is the trajectory suite reading the P8 live logs.

Zero spend: this reads committed files. It never calls a model.
"""

import json
from pathlib import Path

import pytest

from engine.contracts.validate import check_runlog_payloads
from engine.runlog import assert_seq_gapless

ROOT = Path(__file__).resolve().parents[2]
MILESTONE = ROOT / "docs" / "milestones" / "p11-diagnostic"

RUNS = {"claim_extraction": MILESTONE / "runs" / "claim-extraction-run_0006.jsonl",
        "poison": MILESTONE / "runs" / "poison-run_0007.jsonl"}
# The baselines P11's run produced, FROZEN into the milestone (B50): the
# live evals/ copies are overwritten by every later funded re-measure, and
# this suite carries the P11 acceptance clause, not the current state —
# reading the live files would have failed the day the B48/B49
# harness-frame fix re-measured them.
BASELINES = {
    "claim_extraction":
        MILESTONE / "baselines" / "claim-extraction-baseline.json",
    "poison": MILESTONE / "baselines" / "poison-baseline.json"}


def _records(path: Path) -> list[dict]:
    return [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.mark.parametrize("suite", sorted(RUNS))
def test_the_diagnostic_run_left_a_valid_record(suite):
    path = RUNS[suite]
    assert path.exists(), f"{path} — the run's own evidence is missing"
    records = _records(path)
    assert records, "an empty run log proves nothing"

    for record in records:
        check_runlog_payloads(record)
    assert_seq_gapless(records)

    head, tail = records[0], records[-1]
    assert head["record_type"] == "run_start"
    assert tail["record_type"] == "run_end"
    assert tail["run"]["status"] == "completed", \
        "a crashed run must not be presented as the measurement"

    # Eval dollars never enter the production cost series (B34's rule).
    assert head["run"]["mode"] == "regression_bench"

    # The run actually called a model — otherwise this is a scripted
    # rehearsal wearing a live run's name (B33(1)).
    calls = [r for r in records if r.get("record_type") == "agent_call"]
    assert calls, "no agent_call records — nothing was measured live"
    assert all(c["model"].startswith("claude-") for c in calls), \
        "a fake-* model in the record means this was not a live run"


@pytest.mark.parametrize("suite", sorted(RUNS))
def test_the_record_describes_the_baseline_it_produced(suite):
    """The join that makes the pair evidence rather than two files: the
    run log's clock and the baseline's `at` must agree, or the record
    documents some other run."""
    baseline = json.loads(BASELINES[suite].read_text(encoding="utf-8"))
    records = _records(RUNS[suite])
    stamps = {r["ts"][:10] for r in records}
    assert baseline["at"][:10] in stamps, (
        f"{suite}: baseline at={baseline['at']} does not fall on any day in "
        f"its run log {sorted(stamps)} — these are not the same measurement")


def test_the_cost_record_reconciles_with_the_run_logs():
    """A cost actual nobody can re-derive is a claim, not a record."""
    actuals = (MILESTONE / "cost-actuals.md").read_text(encoding="utf-8")
    total = 0.0
    calls = 0
    for path in RUNS.values():
        for record in _records(path):
            if record.get("record_type") == "agent_call":
                total += record["cost_usd"]
                calls += 1
    assert f"{total:.4f}" in actuals, (
        f"summed cost {total:.4f} appears nowhere in cost-actuals.md")
    assert str(calls) in actuals, f"call count {calls} is not recorded"


def test_every_recorded_miss_names_its_cause():
    """THE clause: every miss in BOTH model-scored suites carries a cause
    drawn from the closed taxonomy, and the counts reconcile — no miss
    undescribed, none invented."""
    from engine.evals.cases import _DROP_MARKERS

    known = {c for c, _ in _DROP_MARKERS} | {
        "not_extracted", "tiered_down", "verifier_cleared"}

    for suite, path in BASELINES.items():
        baseline = json.loads(path.read_text(encoding="utf-8"))
        misses, detail = baseline["misses"], baseline["miss_detail"]
        assert misses, f"{suite}: no misses — this clause would be vacuous"
        assert sorted(detail) == sorted(misses)
        assert sum(baseline["causes"].values()) == len(misses)
        for case_id, entry in detail.items():
            assert entry["cause"] in known, \
                f"{suite}/{case_id}: cause {entry['cause']!r} is off-taxonomy"
            assert entry["unmarked_warnings"] == [], \
                f"{suite}/{case_id}: a warning the taxonomy cannot name"


def test_every_drop_cause_is_warranted_by_a_quoted_warning():
    """What converts "recorded cause" into "EVIDENCED cause". A drop must
    quote the warning that caused it; `not_extracted` must show an empty
    parse AND a recorded token count, so "the model said nothing" is a
    reading of the wire rather than an inference from silence (B48)."""
    from engine.evals.cases import _DROP_MARKERS

    markers = dict(_DROP_MARKERS)
    for suite, path in BASELINES.items():
        baseline = json.loads(path.read_text(encoding="utf-8"))
        for case_id, entry in baseline["miss_detail"].items():
            cause = entry["cause"]
            if cause in markers:
                assert any(markers[cause] in w for w in entry["warnings"]), (
                    f"{suite}/{case_id}: cause {cause!r} with no warning "
                    "quoting it — a label without its evidence")
            elif cause == "not_extracted":
                assert entry.get("n_claims", 0) == 0
                assert entry.get("output_tokens") is not None, (
                    f"{suite}/{case_id}: 'never extracted' with no token "
                    "count is exactly the P10-F16 inference, again")
