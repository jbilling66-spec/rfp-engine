"""The live re-baseline arm (B40/D6) — the only eval path that can spend.

Two suites read a recorded baseline behind a dual-fingerprint guard
(prompts + cases). Both refuse the comparison the moment either moves,
which is the design working: a prompt edit costs a live re-measure,
because the recorded numbers stop describing the shipped prompt. This
module is how that re-measure is performed — deliberately, by name, with
the run logged as `mode="regression_bench"` so eval dollars can never
enter a production cost series.

Three properties are structural rather than remembered:

  1. **A scripted re-baseline is refused.** Under a FakeCaller the
     extractor returns whatever the script says, so the recorded number
     would be the script's recall wearing the model's name. `--live` is
     required, and its absence is a named refusal, not a quiet fallback.
  2. **The write closes its own loop.** After writing, the baseline is
     re-read through `check_baseline()`; a baseline that cannot satisfy
     its own guard is deleted and the run reported as failed. Otherwise a
     re-measure could leave behind a file that stales `make eval` — the
     exact state it was run to clear.
  3. **The caller is injected.** `rebaseline()` takes `make_caller`, so
     the whole arm — case load, suite run, baseline write, guard re-read
     — is exercised offline in the suite with a scripted caller writing
     to a tmp path. Only the LiveCaller construction is live-only, and
     that has its own refusal proofs (B30(e)). Shipping just the refusal
     would be the refusal-is-not-delivery trap.
"""

import json
from pathlib import Path

from engine.evals import claim_extraction as _claim_extraction
from engine.kb import KBStore
from engine.runlog import RunLogger
from engine.validation import poison as _poison

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WORKSPACE = ROOT / "pursuits" / "eval-live"


class RebaselineRefused(RuntimeError):
    """The re-measure did not happen, and no baseline was written."""


# Each entry names the module that owns its cases, baseline and guard —
# the arm never reimplements a suite's scoring, it only drives it.
SUITES = {
    "poison": {
        "module": _poison,
        "runner": "run_poison_suite",
        "headline": ("recall", "precision"),
    },
    "claim_extraction": {
        "module": _claim_extraction,
        "runner": "run_extraction_suite",
        "headline": ("claim_extraction_recall", "claim_over_extraction_rate"),
    },
}


def _next_run_id(workspace: Path) -> str:
    runs = workspace / "runs"
    existing = {p.name for p in runs.glob("run_*")} if runs.exists() else set()
    n = 1
    while f"run_{n:04d}" in existing:
        n += 1
    return f"run_{n:04d}"


def history_path(baseline_path: Path) -> Path:
    return Path(baseline_path).with_name("history.jsonl")


def append_history(baseline_path: Path, *, spec: dict,
                   source: str | None = None, run_id: str | None = None,
                   report: dict | None = None) -> Path | None:
    """Append the baseline being REPLACED to history.jsonl, before the
    overwrite (P11-C5).

    `rebaseline()` writes the baseline unconditionally, so before this the
    number it replaced was simply gone — and extraction recall has already
    moved once between cycles (0.8235 -> 0.7059). A recall series of one
    point cannot distinguish a regression from variance, which is the
    question the third measurement exists to answer.

    Append-only and additive: this never edits a baseline, and a missing
    history file is a first run, not an error."""
    prior = report
    if prior is None:
        path = Path(baseline_path)
        if not path.exists():
            return None
        prior = json.loads(path.read_text(encoding="utf-8"))

    line = {"at": prior.get("at"),
            "suite": prior.get("suite"),
            "headline": {k: prior.get(k) for k in spec["headline"]}}
    # EVERY lock the baseline carried, not a hardcoded three: the seam
    # was written at C5 with the triad and never revisited when C7 added
    # code_fingerprint, so the archived number could not prove which
    # scorer produced it — the argument that made the fourth lock
    # mandatory in baselines, lost at the archive step (B49/F-2).
    line.update({k: prior[k] for k in sorted(prior)
                 if k.endswith("_fingerprint")})
    # Provenance, never dressed up as a measurement — and never absent:
    # the committed histories gained an unattributable line at C8 (same
    # numbers, same clock, no source — two identical observations
    # readable as a property, the exact B43a shape). Attribution order:
    # the run that PRODUCED the archived number (recorded in the baseline
    # itself since B49), a caller-supplied run_id, a caller-supplied
    # source, then an explicit archived-without-provenance label. A new
    # run's id must never be stamped onto the number it replaced.
    if prior.get("run_id"):
        line["run_id"] = prior["run_id"]
    elif run_id:
        line["run_id"] = run_id
    if source:
        line["source"] = source
    elif "run_id" not in line:
        line["source"] = ("archived at rebaseline; the outgoing baseline "
                          "predates run_id recording (B49)")

    out_path = history_path(baseline_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(line, sort_keys=True) + "\n")
    return out_path


def rebaseline(name: str, *, make_caller, workspace: Path = DEFAULT_WORKSPACE,
               at: str, baseline_path: Path | None = None,
               engine_version: str = "0.1.0", out=print) -> dict:
    """Run one suite live and write its baseline. Returns the report plus
    the paths written, so the caller can report cost and record the run."""
    if name not in SUITES:
        raise RebaselineRefused(
            f"unknown suite {name!r} — known: {', '.join(sorted(SUITES))}")
    spec = SUITES[name]
    module = spec["module"]
    path = Path(baseline_path) if baseline_path else module.BASELINE_PATH

    cases = module.load_cases()
    store = KBStore(ROOT / "kb")
    workspace = Path(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    run_id = _next_run_id(workspace)
    log = RunLogger(workspace, run_id=run_id, pursuit_id="eval")
    log.run_start(mode="regression_bench", engine_version=engine_version,
                  config={"suite": name, "n_cases": len(cases)},
                  kb_snapshot=store.snapshot())
    caller = make_caller(log)
    out(f"  {name}: {len(cases)} cases -> {run_id}")
    try:
        report = getattr(module, spec["runner"])(store, caller, cases, at=at)
    except BaseException:
        # The run log closes even on a crash: a partial live run still
        # spent money, and the record of what it spent is what makes the
        # next attempt honest (P8's crashed attempt 1 cost $1.91 and its
        # trace is why the scalar-wire bug was findable).
        log.run_end(status="failed")
        raise
    log.run_end(status="completed")

    # The baseline records the run that produced it, so the day it is
    # replaced its history line carries true provenance instead of the
    # replacing run's id — or nothing (B49/F-2).
    report["run_id"] = run_id

    # Preserve the number about to be replaced, BEFORE the overwrite. A
    # crashed run reaches neither this line nor the write, so history never
    # gains an entry for a baseline that still stands.
    append_history(path, spec=spec)
    module.write_baseline(report, path)
    try:
        module.check_baseline(path, cases=cases)
    except module.BaselineMismatch as exc:
        path.unlink(missing_ok=True)
        raise RebaselineRefused(
            f"the baseline just written does not satisfy its own guard "
            f"({exc}) — nothing was left behind; something moved mid-run"
        ) from exc

    for key in spec["headline"]:
        out(f"    {key}: {report[key]}")
    return {"suite": name, "report": report, "baseline_path": path,
            "run_path": log.path, "run_id": run_id}
