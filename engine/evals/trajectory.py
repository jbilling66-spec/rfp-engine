"""Trajectory suite (EVAL_SUITE Tier 2): score the RUN LOG, not the
output. "Component metrics can all pass while the *path* is wrong" — a
drafter citing cards it never opened is fabricated provenance, and only
the trace can see it.

Seven assertion verbs are pre-specified by schemas/eval-case.schema.json
and had zero users before P10; this evaluator implements them.

One structural note that shapes the whole suite: the retrieval emitter
REFUSES to write a citation outside the opened set (engine/kb/retrieve.py
raises ContractError at write time), so a violating trace cannot be
produced by running the engine. Violations are therefore planted as
hand-built record lists — the fixture IS the record list — and the clean
traces come from the committed P8 live run. Both halves matter: without
the planted violation the assertion could never fire, and without the
real trace it could never be trusted.
"""

import json
from pathlib import Path

from engine.evals.cases import load_cases, rate

ROOT = Path(__file__).resolve().parents[2]
CASES_PATH = ROOT / "evals" / "trajectory" / "cases.json"
TRACES_DIR = ROOT / "evals" / "trajectory" / "traces"
LIVE_RUNS = ROOT / "docs" / "milestones" / "p8-live-run" / "runs"

# P2-36 (P26b-3): floors are the committed counts — 8 cases, and the
# CI slice drafts 8 sections.
MINIMUM_N = {"cases": 8, "drafted_sections": 8}


def load_trace(name: str) -> list[dict]:
    """A trace is either a committed planted fixture or one of the P8
    live run logs — real traffic, so a clean assertion means something.

    M-20 (P26b-3): the name is a case-supplied string; it resolves INSIDE
    one of the two directories or refuses, and a name found in neither
    is a typed refusal naming both — never a silent fall-through to a
    path in docs/milestones/."""
    from engine.contracts import within

    for directory in (TRACES_DIR, LIVE_RUNS):
        path = within(directory, name)
        if path.exists():
            return [json.loads(line) for line in
                    path.read_text(encoding="utf-8").splitlines()
                    if line.strip()]
    raise FileNotFoundError(
        f"trace {name!r} is in neither {TRACES_DIR} nor {LIVE_RUNS}")


def _kb_lines(records):
    return [r for r in records if r.get("record_type") == "kb_retrieval"]


def check_assertion(records: list[dict], assertion: dict) -> tuple[bool, str]:
    """Return (holds, detail). `holds` is what the trace DOES; whether
    that is a pass depends on the case's expectation."""
    kind = assertion["assert"]
    value = assertion.get("value")

    if kind == "cited_subset_of_opened":
        for line in _kb_lines(records):
            kb = line["kb"]
            cited = set(kb.get("cards_cited") or ())
            opened = set(kb.get("cards_opened") or ())
            if not cited <= opened:
                return False, (f"seq {line['seq']}: cited "
                               f"{sorted(cited - opened)} never opened")
        return True, "every citation was opened first"

    if kind == "no_excluded_card_opened":
        excluded = {kb_id for line in _kb_lines(records)
                    for kb_id in (line["kb"].get("excluded") or ())}
        opened = {kb_id for line in _kb_lines(records)
                  for kb_id in (line["kb"].get("cards_opened") or ())}
        leaked = excluded & opened
        if leaked:
            return False, f"excluded card(s) opened: {sorted(leaked)}"
        return True, f"{len(excluded)} excluded card(s), none opened"

    if kind == "gap_emitted":
        gaps = [r for r in records if r.get("record_type") == "gap"]
        if gaps:
            return True, f"{len(gaps)} gap record(s) emitted"
        return False, "no gap record emitted"

    if kind == "max_tool_calls":
        calls = sum(1 for r in records if r.get("record_type") == "agent_call")
        if calls <= value:
            return True, f"{calls} agent calls <= {value}"
        return False, f"{calls} agent calls > {value}"

    if kind == "max_cost_usd":
        # cost_usd is a TOP-LEVEL field on the agent_call record, not
        # nested under an "agent_call" key — reading the wrong path summed
        # to $0.00 and made this assertion vacuously true for every run
        # (caught by its own can-fail test).
        calls = [r for r in records if r.get("record_type") == "agent_call"]
        if not calls:
            return False, "no agent_call records — cost is unmeasurable here"
        # M-21 (P26b-3): a call that carries no cost_usd is not free — it
        # is unmeasurable, the same verdict as no calls at all.
        unpriced = [r.get("seq") for r in calls if "cost_usd" not in r]
        if unpriced:
            return False, (f"agent_call records {unpriced} carry no cost_usd "
                           "— cost is unmeasurable here")
        total = sum(r["cost_usd"] for r in calls)
        if round(total, 6) <= value:
            return True, f"${total:.4f} <= ${value}"
        return False, f"${total:.4f} > ${value}"

    if kind == "stage_reached":
        stages = {r.get("stage") for r in records}
        if value in stages:
            return True, f"stage {value} present"
        return False, f"stage {value} never reached"

    if kind == "no_unflagged_tier1":
        for line in records:
            if line.get("record_type") != "validation":
                continue
            v = line["validation"]
            if (v.get("claim_tier") == 1
                    and v.get("result") not in ("block", "flag")):
                return False, (f"seq {line['seq']}: tier-1 claim with "
                               f"result {v.get('result')!r}")
        return True, "no tier-1 claim passed unflagged"

    raise ValueError(f"unknown trajectory assertion {kind!r}")


def slice_call_pattern(workdir: Path | None = None) -> dict:
    """P0-9's clause-2 inputs (P26a Group E): run the CI slice (FakeCaller,
    dry_run, synthetic prices) into a scratch workspace and measure the
    ENGINE'S call pattern per drafted section — cost and agent calls. The
    numbers are deterministic for a given engine, so release-to-release
    movement is a change in how many calls the pipeline makes, which is
    exactly what the clause asks about; they are never a live cost."""
    import tempfile

    from engine.cli.slice import run_slice
    from engine.runlog import read_run

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(workdir) if workdir else Path(tmp) / "ws"
        result = run_slice(workspace, out=lambda *_a, **_k: None)
        if result.status != "ok":
            return {"status": result.status, "problems": result.problems}
        root = workspace / "pur_demo"
        cost, calls = 0.0, 0
        for run_file in sorted((root / "runs").glob("*/run.jsonl")):
            for record in read_run(run_file):
                if record.get("record_type") == "agent_call":
                    calls += 1
                    cost += float(record.get("cost_usd", 0.0))
        annotated = json.loads(
            (root / "drafts" / "annotated-draft.json").read_text("utf-8"))
        drafted = [s for s in annotated["sections"]
                   if s.get("draft_status") == "drafted"]
        n = len(drafted)
        return {"status": "ok", "drafted_sections": n,
                "agent_calls": calls, "cost_usd": round(cost, 6),
                "cost_per_section": rate(
                    cost, n, floor=MINIMUM_N["drafted_sections"],
                    lane="trajectory", of="drafted sections", digits=6),
                "tool_calls_per_section": rate(
                    calls, n, floor=MINIMUM_N["drafted_sections"],
                    lane="trajectory", of="drafted sections")}


def evaluate_trajectory_set(path: Path = CASES_PATH) -> dict:
    cases = load_cases(path)
    passed = 0
    failures: list[str] = []
    detected: list[str] = []

    for case in cases:
        records = load_trace(case["input"]["files"][0])
        expect_violation = case["expected"].get("must_flag", False)
        case_ok = True
        for assertion in case["expected"]["trajectory_assertions"]:
            holds, detail = check_assertion(records, assertion)
            # must_flag means the trace is PLANTED to violate: the
            # assertion is supposed to report False, and a True there is
            # the evaluator going blind.
            if holds == expect_violation:
                case_ok = False
                failures.append(
                    f"{case['case_id']}/{assertion['assert']}: {detail}")
            elif expect_violation:
                detected.append(f"{case['case_id']}/{assertion['assert']}")
        passed += int(case_ok)

    return {
        "suite": "trajectory",
        "n_cases": len(cases),
        "n_violation_cases": sum(1 for c in cases
                                 if c["expected"].get("must_flag")),
        "pass_rate": rate(passed, len(cases), floor=MINIMUM_N["cases"],
                          lane="trajectory", of="cases"),
        "minimum_n": dict(MINIMUM_N),
        "violations_detected": sorted(detected),
        "failures": sorted(failures),
    }
