"""Case files, fingerprints, and report writes — the parts every harness
carried its own copy of (B40/D2). Extraction rule: delegate-only. The
existing harnesses keep their public names and signatures, and the
recorded baselines stay byte-identical because every fingerprint here
hashes the same bytes/objects the originals hashed.
"""

import hashlib
import json
import textwrap
from pathlib import Path

from engine.contracts import validate


def load_cases(path: Path) -> list[dict]:
    """Load a suite file and validate every case against the eval-case
    contract before anything runs — a malformed case fails the load, not
    the middle of a measure."""
    cases = json.loads(Path(path).read_text(encoding="utf-8"))
    for case in cases:
        validate("eval_case", case)
    return cases


def object_fingerprint(obj) -> str:
    """sha256 over the sort-keys JSON of a live object (the cases that
    RAN, a pattern registry) — derived from what executed, never from a
    path, so a saver and a checker cannot compute it from different
    sources."""
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True).encode("utf-8")).hexdigest()


def files_fingerprint(*paths: Path) -> str:
    """sha256 over the raw bytes of the named files, in order (prompt
    files, spec files) — the lock a recorded measure stands behind."""
    digest = hashlib.sha256()
    for path in paths:
        digest.update(Path(path).read_bytes())
    return digest.hexdigest()


def model_fingerprint(*agents: str) -> str:
    """The third lock (B43/P10-F14): WHICH MODELS ran the measure, and
    under what per-agent settings.

    The prompts+cases pair was the v1 lesson — a guard watching only the
    prompt compares "clean" over a moved corpus. It has a blind side of
    its own: repoint a tier at a different model, or change an agent's
    config.yaml, and both existing fingerprints still match while the
    recorded number describes a system that no longer exists. That blind
    side was found by asking why an eval number was reproducible to four
    decimals over a changed prompt (B43).

    Deliberately hashes the agent config WHOLE rather than an enumerated
    list of settings: the next setting worth locking should be covered
    the day it is added, not the day someone remembers to extend this.

    Derived from live config rather than a path, so the writer and the
    checker cannot read different sources."""
    import yaml

    from engine.llm.config import PROMPTS_DIR, model_prices

    configs = {}
    for agent in agents:
        agent_yaml = PROMPTS_DIR / agent / "config.yaml"
        configs[agent] = (yaml.safe_load(
            agent_yaml.read_text(encoding="utf-8")) or {}
            if agent_yaml.exists() else None)
    return object_fingerprint({"tiers": model_prices()["tiers"],
                               "agents": configs})


# The FOURTH lock (P11-C7). Prompts, cases and model config are all data;
# none of them covers the CODE that turns a model response into a number.
# Change parse_extraction_wire — loosen the verbatim match, say — and both
# recall numbers move while all three existing fingerprints still match, so
# `make eval` compares a new system against an old number and reports
# clean. That is the same class of blind side model_fingerprint was added
# to close, one layer further in.
#
# FUNCTION-level, not file-level, and deliberately: hashing all of
# validate.py would stale a $3 baseline every time its drafting or voice
# halves changed for unrelated reasons, and a guard that cries wolf is one
# people learn to silence.
_SCORING_ROSTER = (
    ("engine.validation.claims", "parse_extraction_wire"),
    ("engine.validation.claims", "build_extraction_prompt"),
    ("engine.validation.audit", "build_verify_prompt"),
    ("engine.validation.audit", "parse_verdict_wire"),
    ("engine.validation.audit", "audit_claim"),
    ("engine.validation.validate", "run_claim_audit"),
    ("engine.evals.cases", "miss_cause"),
)


def _semantic_source(src: str) -> str:
    """The function's STRUCTURE, with comments and docstrings removed.

    Hashing raw source was the first attempt and it was wrong: editing a
    comment in a rostered function demanded a live re-measure to clear the
    guard. A lock that costs $3 to satisfy after a typo fix is one people
    route around, and the whole argument for function-level hashing was
    that it should not cry wolf.

    ast.dump never carries comments; docstrings survive as leading string
    Expr nodes, so they are stripped explicitly. What remains moves if and
    only if the code does."""
    import ast

    tree = ast.parse(textwrap.dedent(src))
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if (isinstance(body, list) and body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            body.pop(0)
    return ast.dump(tree)


def code_fingerprint(*extra: tuple[str, str]) -> str:
    """Hash the STRUCTURE of every function that decides what a suite
    scores — the fourth baseline lock (P11-C7).

    Resolved at call time, so a renamed or moved function raises here
    rather than silently hashing nothing: an unresolvable roster entry is
    a broken guard, not an empty one."""
    import importlib
    import inspect

    sources = {}
    for module_name, attr in (*_SCORING_ROSTER, *extra):
        module = importlib.import_module(module_name)
        try:
            target = getattr(module, attr)
        except AttributeError as exc:
            raise AttributeError(
                f"code_fingerprint roster names {module_name}.{attr}, which "
                f"no longer exists — a renamed scorer must be renamed in the "
                f"roster too, or the lock silently stops covering it"
            ) from exc
        sources[f"{module_name}.{attr}"] = _semantic_source(
            inspect.getsource(target))
    return object_fingerprint(sources)


# The warning strings parse_extraction_wire emits when it discards a row.
# Shared because BOTH model-scored suites need to distinguish "the model
# never produced this claim" from "the model produced it and code threw it
# away" — the distinction P10-F16 found the extraction suite was blind to,
# and the poison suite was blind to it in the same way.
#
# EVERY drop site in parse_extraction_wire must appear here. A drop with no
# marker does not report as "unknown" — it falls through to `not_extracted`
# and reads as "the model never produced this claim", which is exactly the
# P10-F16 misattribution wearing a different mask. The fifth entry below was
# missing for two phases (B46): an invalid tier discarded the row silently.
# `test_every_warning_the_parser_emits_is_nameable_by_the_taxonomy` reads
# the emitter's source and fails when a new drop site lands without one
# (the citation named a nonexistent test until the pre-P12 audit, B49).
# The section title BOTH model-scored harnesses hand the auditor (B50).
# Human-shaped and constant, mirroring production's Path B (a human title,
# None-keyed prose): P11 proved that passing the case id here makes the
# model echo it as slot_id and code drops a CORRECT claim (B48) — the
# harness frame, not the model, caused both recorded extraction misses.
SECTION_TITLE = "Drafted section"

_DROP_MARKERS = (
    ("dropped_verbatim", "not present in delivered prose"),
    ("wire_unparseable", "wire unparseable"),
    ("dropped_malformed", "malformed claim row"),
    ("dropped_unknown_slot", "unknown slot"),
    ("dropped_invalid_tier", "invalid tier"),
)

# Warnings that are NOT drops. parse_extraction_wire also degrades a claim
# whose proposed fact_sheet_ref is not in the catalog — the claim SURVIVES
# with ref=None. Marking it as a drop cause would blame the parser for a
# claim it kept, so it is allowlisted here rather than left to look like an
# oversight the next reader "fixes".
_DEGRADE_MARKERS = ("is not in the catalog",)


def miss_cause(*, warnings: list[str], n_claims: int, tiers: list[int],
               reached_verifier: bool = False) -> str:
    """Name WHICH subsystem lost the claim.

    Ordered so a guard drop is reported as a guard drop: it is the cause
    that reads as "the model never saw it" while actually meaning "the
    model saw it and code threw it away", and mistaking the two sends the
    next fix to the wrong place entirely.

    reached_verifier distinguishes the poison suite's fourth cause: a
    claim correctly extracted AND tiered, which the verifier then cleared.
    That is a verification failure, not an extraction one — the exact
    split the extraction suite was built to expose (B40/D7).

    Returns ONE cause by priority. When a case drops rows for more than one
    reason the roll-up under-counts, so callers record `causes_matched`
    alongside it — see matched_causes()."""
    for cause, marker in _DROP_MARKERS:
        if any(marker in w for w in warnings):
            return cause
    if not n_claims:
        return "not_extracted"
    if 1 not in tiers:
        return "tiered_down"
    if reached_verifier:
        return "verifier_cleared"
    return "tiered_down"


def matched_causes(warnings: list[str]) -> list[str]:
    """EVERY drop cause present, not just the winning one.

    miss_cause collapses to the first marker by priority, so a case that
    dropped one row verbatim and another for a bad tier reports only
    `dropped_verbatim` — and the tier signal vanishes from the roll-up.
    The full set is cheap to record and is what makes a `causes` histogram
    an upper bound one can reason about rather than a silent partition."""
    return [cause for cause, marker in _DROP_MARKERS
            if any(marker in w for w in warnings)]


def unmarked_warnings(warnings: list[str]) -> list[str]:
    """Warnings matching neither a drop marker nor a known degrade.

    An empty list is the invariant. A non-empty one means the emitter grew
    a warning the taxonomy cannot name — which is how P10-F16 stayed
    invisible — so both suites surface it in the report instead of letting
    it fall through to `not_extracted`."""
    known = tuple(m for _, m in _DROP_MARKERS) + _DEGRADE_MARKERS
    return [w for w in warnings if not any(m in w for m in known)]


# Enough of the wire to see whether the model answered and what it
# proposed; short enough that a baseline stays a diff-reviewable record
# rather than a transcript dump. cX cycle 2's misses ran ~110 output
# tokens, so this holds a whole one.
WIRE_EXCERPT_CHARS = 700


def wire_excerpt(text: str | None) -> str | None:
    """The captured wire, truncated with the truncation made visible.

    Recorded ONLY for misses, and only in the eval baselines, whose cases
    are synthetic (CLAUDE.md rule 1) — this is model output about invented
    prose, never client material."""
    if text is None:
        return None
    if len(text) <= WIRE_EXCERPT_CHARS:
        return text
    return text[:WIRE_EXCERPT_CHARS] + f"… [+{len(text) - WIRE_EXCERPT_CHARS} chars]"


def cause_counts(causes: list[str]) -> dict:
    counts: dict[str, int] = {}
    for cause in causes:
        counts[cause] = counts.get(cause, 0) + 1
    return dict(sorted(counts.items()))


def write_report(report: dict, path: Path) -> Path:
    """The one report shape on disk: indent=1, sort_keys, trailing
    newline — byte-stable for the same report, diff-friendly for a
    human."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n",
                    encoding="utf-8")
    return path
