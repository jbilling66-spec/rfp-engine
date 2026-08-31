"""Strategy-stage harness (P5): chains the P4 research package (runs
0001/0002, findings in the brief) with a scripted strategist run (run_0003)
and an optional headless Gate-1 decision.

The scripted wires are DERIVED from the prompt (the packages.py/pursuits.py
pattern): the generate fake reads back the findings block the stage actually
inlined in the wrap_findings frame and cites those sources verbatim —
fixture, prompt, frame, and script cannot drift, and every cite is real by
construction. The frame regex here is the single source the frame-drift
assertions in test_themes key on. Goldens are hand-transcribed pack facts
(ANCHOR_CITE / ANCHOR_MARKER restate tests/research/fixtures/research-pack.md),
never derived by the code under test.
"""

import json
import re

from engine.kb import KBStore
from engine.llm import FakeCaller, TracedCaller, effective_config
from engine.runlog import RunLogger
from engine.strategy import run_win_themes
from engine.version import engine_version
from tests.research.fixtures.pursuits import run_research_package

GATE_AT = "2026-08-01T12:00:00Z"  # the injected literal (B22(8)); no wall-clock
ACTOR = "test_pursuit_lead"

# Hand-transcribed goldens (restated pack facts):
ANCHOR_CITE = "https://example.org/synthetic/strategy-brief"
ANCHOR_MARKER = "multi-year clinical systems modernization program"

N_GENERATED = 7        # the generate fake always emits exactly 7 (corpus-independent)
KEEP_INDEXES = (1, 2)  # the judge fake keeps candidates 1 and 2
KILL_REASON = "generic — does not use the buyer research"

_FINDINGS_RX = re.compile(
    r'<research_findings label="semi_trusted">\n(.*?)\n</research_findings>',
    re.S)
_BRIEF_RX = re.compile(
    r'<bid_brief_context label="semi_trusted">\n(.*?)\n</bid_brief_context>',
    re.S)
_FINDING_LINE_RX = re.compile(r"^- \((\w+)\) (\S+) \| (.*?): (.*)$", re.M)
_CANDIDATE_RX = re.compile(r"^(\d+)\. ", re.M)


def _findings_of(prompt: str) -> list[tuple[str, str, str, str]]:
    frame = _FINDINGS_RX.search(prompt)
    return _FINDING_LINE_RX.findall(frame.group(1)) if frame else []


def make_script(*, n_generate: int = N_GENERATED, keep=KEEP_INDEXES,
                plant_bad_cite: bool = False) -> dict:
    """Build a strategist script. The defaults are the well-behaved fake;
    kwargs produce the misbehaving variants the clamp/gate tests plant."""

    def _generate(prompt: str) -> str:
        found = _findings_of(prompt)
        candidates = []
        for i in range(n_generate):
            _, source, _, claim = found[i % len(found)]
            candidate = {
                "theme": f"Win theme {i + 1}: lead with {claim}",
                "rationale": f"grounded in {source}",
                "cites": [source],
            }
            if plant_bad_cite and i == 0:
                candidate["cites"] = ["https://example.org/not-in-brief"]
            candidates.append(candidate)
        return json.dumps({"candidates": candidates})

    def _judge(prompt: str) -> str:
        n = len(_CANDIDATE_RX.findall(prompt))
        verdicts = []
        for i in range(1, n + 1):
            if i in keep:
                verdicts.append({"candidate": i, "verdict": "keep"})
            else:
                verdicts.append({"candidate": i, "verdict": "kill",
                                 "reason": KILL_REASON})
        return json.dumps({"verdicts": verdicts})

    def _dispatch(prompt: str) -> str:
        return _judge(prompt) if prompt.startswith("Task: judge.") else _generate(prompt)

    return {"win_theme_strategist": _dispatch}


SCRIPT = make_script()


def bare_strategy_run(tmp_root, pursuit, *, script=None):
    """A strategist run over an EXISTING workspace (no intake/research
    rerun) — the refusal-path and post-gate-rerun tests' setup. Returns
    (report, run.jsonl path)."""
    store = KBStore(tmp_root / "kb")
    log = RunLogger(pursuit.root, pursuit.new_run_id(), pursuit.pursuit_id)
    caller = TracedCaller(FakeCaller(script or SCRIPT), log)
    cfg = effective_config()
    log.run_start(mode="dry_run", engine_version=engine_version(), config=cfg,
                  kb_snapshot=store.snapshot(),
                  research_mode=cfg["research_mode"])
    report = run_win_themes(pursuit, caller, log)
    log.run_end(status="completed")
    return report, log.path


def run_strategy_package(tmp_root, *, script=None, gate="approved", edits=None,
                         notes=None, actor=ACTOR, at=GATE_AT,
                         package_id="pdf"):
    """P4 research package (runs 0001/0002) → strategist run (run_0003) →
    optional headless Gate-1 decision. gate=None stops before the gate and
    the run ends awaiting_gate; a refused stage still closes the run.
    package_id defaults to the P5-era pdf chain (frozen suites depend on
    it); P6 threads xlsx-family packages through for Path-A pursuits."""
    pursuit, _ = run_research_package(tmp_root, package_id=package_id)
    store = KBStore(tmp_root / "kb")  # reopened from disk (resume precedent)
    log = RunLogger(pursuit.root, pursuit.new_run_id(), pursuit.pursuit_id)
    caller = TracedCaller(FakeCaller(script or SCRIPT), log)
    cfg = effective_config()
    log.run_start(mode="dry_run", engine_version=engine_version(), config=cfg,
                  kb_snapshot=store.snapshot(),
                  research_mode=cfg["research_mode"])
    report = run_win_themes(pursuit, caller, log)
    if gate is None or report.status == "refused":
        log.run_end(status="awaiting_gate" if report.status == "complete"
                    else "completed")
        return pursuit, report
    from engine.strategy import approve_gate1
    approve_gate1(pursuit, log, decision=gate, actor=actor, at=at,
                  notes=notes, edits=edits)
    log.run_end(status="completed")
    return pursuit, report
