"""The anonymization eval harness (E4/R13, EVAL_SUITE component row).

Runs every case in a suite file through the REAL ingestion pipeline into a
throwaway store, then checks that no labeled identifier and no
must_not_contain string is retrievable. A case whose ingestion BLOCKED
passes — the gate holding is the desired outcome; leakage is the failure.

The result is a boolean, never a rate (R13): one leaked identifier fails
the suite, and the failure list names the case and the string so a named
human can act on it.

Offline the model is a scripted FakeCaller, so this suite proves the
pipeline and its code gates; the live readers' own recall is measured
with the same harness at RFP_LIVE by swapping the script for the real
caller. Eval docs never enter a real store (cases are kept outside the KB
so evals measure capability, not memorization).

P28 (P1-4): the live arm cannot call itself live. `live=True` is accepted
only when RFP_LIVE=1 is set AND the caller factory was built by
`live_caller_factory` over a LiveCaller (P2-37's rule, this lane); a
scripted result is never recorded. The recorded live measure lives in
`evals/anonymization/live-record.json`, keyed to a fingerprint of the
corpus, and the release record reads it as `measures.live` — fresh, or
`not_measured` with the reason. A1's acceptance line is that record.
"""

import importlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from engine.evals import cases as _shared
from engine.kb.anonymize import normalize_text
from engine.kb.ingest import SourceDoc, ingest_document
from engine.kb.read import read_source
from engine.kb.store import KBStore
from engine.llm import FakeCaller, TracedCaller
from engine.runlog import RunLogger
from engine.workspace.pursuit import mint_run_id

# P2-36 (P26b-3): the floor is the committed case count — a boolean
# suite over a shrunken corpus is a vacuous pass by another route.
MINIMUM_N = {"cases": 42}

ROOT = Path(__file__).resolve().parents[2]
CASES_PATH = ROOT / "evals" / "anonymization" / "cases.json"
# P28: written ONLY by the live arm (record_live_result); read by the lane.
LIVE_RECORD_PATH = ROOT / "evals" / "anonymization" / "live-record.json"


class AnonymizationLiveRefused(RuntimeError):
    """The live arm did not run, or its result was not recorded — and says why."""

_META_LINE = re.compile(r"<!--\s*(.*?)\s*-->", re.DOTALL)


def doc_meta(text: str) -> dict:
    """Parse the doc's metadata comment: `key: value | key: value`."""
    match = _META_LINE.search(text)
    if not match:
        raise ValueError("eval doc has no metadata comment")
    meta = {}
    for part in match.group(1).split("|"):
        key, _, value = part.partition(":")
        meta[key.strip()] = value.strip()
    return meta


_CHUNK_MARKER = re.compile(r"^<<CHUNK (\d+): (.*)>>$", re.MULTILINE)


def _meta_list(meta: dict, key: str) -> list[str]:
    return [v.strip() for v in meta.get(key, "").split(",") if v.strip()]


def meta_identifiers(meta: dict, *, miss: set[str] = frozenset(),
                     truncate: set[str] = frozenset()) -> list[dict]:
    """The ground-truth identifier list the harness metadata declares —
    client, fee, fee_forms (restatements, FEE), contacts (REFERENCE_NAME),
    orgs (ORGANIZATION). `miss` names the classes a scripted reader
    deliberately omits and `truncate` the classes it lists one character
    short (the `miss:` / `truncate:` meta keys — the cross-check cases,
    P28: only the FIRST reader honours them). A `types:` meta key
    (`value=TYPE,...`) retypes an entry — the wrong-type cases."""
    retyped = dict(pair.split("=", 1) for pair in _meta_list(meta, "types")
                   if "=" in pair)
    identifiers = [{"value": meta["client"], "type": "CLIENT"}]
    if meta.get("fee") and "fee" not in miss:
        identifiers.append({"value": meta["fee"], "type": "FEE"})
    if "fee_forms" not in miss:
        identifiers += [{"value": f, "type": "FEE"}
                        for f in _meta_list(meta, "fee_forms")]
    if "contacts" not in miss:
        identifiers += [{"value": c, "type": "REFERENCE_NAME"}
                        for c in _meta_list(meta, "contacts")]
    if "orgs" not in miss:
        identifiers += [{"value": o, "type": "ORGANIZATION"}
                        for o in _meta_list(meta, "orgs")]
    classes = {"CLIENT": "client", "FEE": "fee", "REFERENCE_NAME": "contacts",
               "ORGANIZATION": "orgs"}
    for entry in identifiers:
        entry["type"] = retyped.get(entry["value"], entry["type"])
        if classes.get(entry["type"]) in truncate:
            entry["value"] = entry["value"][:-1]
    return identifiers


def default_script(meta: dict) -> dict:
    """Competent scripted readers for ONE document — BOTH agents (P28):
    the annotator names every chunk the engine lists and the identifiers
    the harness metadata declares; the reviewer names the identifiers
    only. Per-document since the v2 wire (P13/C8) — the prompts are built
    from canonical elements, which deliberately exclude the meta comment,
    so ground-truth identifiers must arrive from outside. The `miss:` meta
    key makes the FIRST reader omit a class; the reviewer never reads it —
    that asymmetry is the cross-check's proof. Deliberately does NOT
    descriptorize anything — the code post-pass must earn the pass."""
    miss = set(_meta_list(meta, "miss"))
    truncate = set(_meta_list(meta, "truncate"))

    def respond(prompt: str) -> str:
        annotations = [
            {"chunk": int(m.group(1)), "summary": m.group(2).strip(),
             "section_types": [], "type_tags": []}
            for m in _CHUNK_MARKER.finditer(prompt)
        ]
        return json.dumps({
            "chunk_annotations": annotations,
            "qa_pairs": [],
            "identifiers": meta_identifiers(meta, miss=miss,
                                            truncate=truncate),
            "client_descriptor": meta.get("descriptor", "an organization"),
        })

    def review(prompt: str) -> str:
        return json.dumps({"identifiers": meta_identifiers(meta)})

    return {"ingestion_agent": respond, "anonymization_reviewer": review}


@dataclass
class AnonymizationResult:
    """The suite's verdict plus what the record carries (P28): the boolean,
    the named failures, and how many cases the pipeline DELIVERED vs
    REFUSED — a block passes the leakage check by construction, so the
    count is the honest companion to the pass."""
    ok: bool
    failures: list[str]
    n_cases: int
    n_blocked: int
    blocked: list[str]
    mode: str = "scripted"  # "live" only through the gated arm (P28)


def evaluate_anonymization_set(cases_path: Path, workdir: Path,
                               script_factory=None, *,
                               caller_factory=None) -> tuple[bool, list[str]]:
    """Boolean over the whole suite + the named failures. Any failure is an
    incident for the audit human, not a trend point. (The pair every
    caller reads; run_anonymization_set carries the counts too.)"""
    result = run_anonymization_set(cases_path, workdir, script_factory,
                                   caller_factory=caller_factory)
    return result.ok, result.failures


def live_caller_factory(live_caller, *, prices: dict, budget):
    """The caller factory the live arm accepts (P28, P2-37's pattern for
    this lane): built ONLY over a LiveCaller, wrapping it in a
    TracedCaller per case with the shared budget — an untraced live call
    must not exist, and a scripted caller must never wear the live name."""
    from engine.llm.caller import TracedCaller
    from engine.llm.live import LiveCaller

    if not isinstance(live_caller, LiveCaller):
        raise AnonymizationLiveRefused(
            "live_caller_factory needs a LiveCaller — got "
            f"{type(live_caller).__name__}; a scripted caller cannot "
            "produce a live measure")

    def make_caller(log):
        return TracedCaller(live_caller, log, prices=prices, budget=budget)

    make_caller.live = True
    return make_caller


def _refuse_unless_live(caller_factory) -> None:
    from engine.llm.caller import live_allowed

    if not live_allowed():
        raise AnonymizationLiveRefused(
            "live=True refused: RFP_LIVE=1 is not set — the same gate the "
            "live caller's constructor honours (B30(e)); nothing was "
            "measured under the live name")
    if not getattr(caller_factory, "live", False):
        raise AnonymizationLiveRefused(
            "live=True refused: the caller factory was not built by "
            "live_caller_factory over a LiveCaller — a bare callable "
            "cannot declare itself live (P2-37, P28)")


def cases_fingerprint(cases_path: Path = CASES_PATH) -> str:
    """The corpus the live record stands behind: the case list plus the
    bytes of every committed document it references (runtime-built
    fixtures are covered by their generator names inside the case list)."""
    cases = _shared.load_cases(Path(cases_path))
    docs = sorted({Path(cases_path).parent / f
                   for case in cases for f in case["input"].get("files", [])
                   if (Path(cases_path).parent / f).is_file()})
    return _shared.object_fingerprint({
        "cases": cases, "docs": _shared.files_fingerprint(*docs)})


def record_live_result(result: AnonymizationResult, *, cases_path: Path,
                       at: str, workspace: str, config_digest: str,
                       path: Path = LIVE_RECORD_PATH) -> Path:
    """Write the live arm's measure — refused for a scripted result (the
    script's pass would wear the model's name). The record carries the
    corpus fingerprint so the lane can tell a fresh measure from a
    stale one."""
    if result.mode != "live":
        raise AnonymizationLiveRefused(
            "recording a scripted anonymization run is refused — the "
            "recorded pass would be the script's wearing the model's name")
    record = {
        "at": at, "workspace": workspace, "config_digest": config_digest,
        "cases_fingerprint": cases_fingerprint(cases_path),
        "n_cases": result.n_cases, "n_blocked": result.n_blocked,
        "blocked": result.blocked, "failures": result.failures,
        "pass": result.ok,
    }
    Path(path).write_text(json.dumps(record, indent=1, sort_keys=True) + "\n",
                          encoding="utf-8")
    return Path(path)


def live_measure(cases_path: Path = CASES_PATH,
                 path: Path = LIVE_RECORD_PATH) -> dict:
    """What the release record says about the LIVE readers (P28): the
    recorded measure when its corpus fingerprint is today's, else
    `not_measured` with the reason. Non-blocking until A1, whose
    acceptance line is `pass` here against the current corpus."""
    if not Path(path).exists():
        return {"status": "not_measured",
                "since": "no live record — A1's run writes it "
                         "(docs/uat/a1-anonymization-live.md)"}
    record = json.loads(Path(path).read_text(encoding="utf-8"))
    if record.get("cases_fingerprint") != cases_fingerprint(cases_path):
        return {"status": "not_measured",
                "since": f"the corpus changed since the recorded run of "
                         f"{record.get('at')} — re-run the live arm"}
    return {"status": "measured", "at": record["at"],
            "n_cases": record["n_cases"], "n_blocked": record["n_blocked"],
            "failures": record["failures"], "pass": record["pass"]}


def run_anonymization_set(cases_path: Path, workdir: Path,
                          script_factory=None, *,
                          caller_factory=None,
                          live: bool = False) -> AnonymizationResult:
    """script_factory(meta) -> script dict builds the per-document scripted
    readers (default_script when omitted) — per-document since the v2
    wire, see default_script. caller_factory(log) -> TracedCaller swaps
    the scripted FakeCaller for a real one (the RFP_LIVE measurement
    path); omitted, the scripted default stands and the suite spends
    nothing. A case whose `expected.status` names a delivery outcome
    (`ingested` | `blocked`) fails when ingestion lands elsewhere — the
    suite pins DELIVERY as well as leakage (P28). live=True is refused
    unless RFP_LIVE=1 is set and caller_factory came from
    live_caller_factory — a bare callable cannot declare itself live."""
    if live:
        _refuse_unless_live(caller_factory)
    cases = _shared.load_cases(Path(cases_path))
    _shared.require_n(len(cases), MINIMUM_N["cases"], lane="anonymization",
                      of="cases")
    failures: list[str] = []
    blocked: list[str] = []
    for case in cases:
        root = Path(workdir) / case["case_id"]
        generator = case["input"].get("generator")
        if generator:
            # Runtime-built fixture (C11 media cases): committed binaries
            # are barred by the tripwire's extraction sweep (B40/D21).
            module_name, _, func_name = generator.partition(":")
            builder = getattr(importlib.import_module(module_name), func_name)
            root.mkdir(parents=True, exist_ok=True)
            doc_path = builder(root / case["input"]["files"][0])
        else:
            doc_path = Path(cases_path).parent / case["input"]["files"][0]
        source = read_source(doc_path)
        text = source.text
        meta = doc_meta(text)

        store = KBStore(root / "kb")
        log = RunLogger(store.root, mint_run_id(store.root / "runs"), "kb")
        script = (script_factory or default_script)(meta)
        caller = (caller_factory(log) if caller_factory is not None
                  else TracedCaller(FakeCaller(script), log))
        doc = SourceDoc(
            doc_id=case["case_id"], text=text,
            source_client=meta["client"],
            source_pursuit=meta.get("pursuit", f"pur_{case['case_id']}"),
            outcome=meta.get("outcome", "unknown"),
            date=meta.get("date", "2026-01-01"),
            authored_by="firm",
            known_identifiers={meta["client"]: "CLIENT"},
            extractor=source.extractor,
            extraction_fingerprint=source.fingerprint,
            media=source.media,
            elements=source.elements,
            source_bytes=doc_path.read_bytes(),
        )
        report = ingest_document(store, caller, log, doc)

        retrievable = retrievable_text(store)
        expected = case.get("expected", {})
        if report.status == "blocked":
            blocked.append(case["case_id"])
        wanted = expected.get("status")
        if wanted and report.status != wanted:
            failures.append(
                f"{case['case_id']}: expected ingestion to be {wanted}, "
                f"it was {report.status}")
        # C11: a document carrying an image must come out media-flagged —
        # a logo or signature is identity the text scan cannot see.
        if (expected.get("media") or {}).get("must_flag") and not report.media_flagged:
            failures.append(
                f"{case['case_id']}: document carries media but the ingest "
                "report is not media-flagged"
            )
        banned = expected.get("labels", []) + expected.get("must_not_contain", [])
        if not banned and not (expected.get("media") or {}).get("must_flag"):
            # M-26 (P26b-3): a case with nothing to assert used to pass
            # silently, indistinguishable from one that held. Named.
            failures.append(
                f"{case['case_id']}: asserts nothing — no label, no needle, "
                "no media flag")
        for needle in banned:
            where = [source for source, text in retrievable.items()
                     if needle.lower() in text]
            if where:
                failures.append(
                    f"{case['case_id']}: {needle!r} is retrievable "
                    f"({', '.join(where)})"
                )
    return AnonymizationResult(ok=not failures, failures=failures,
                               n_cases=len(cases), n_blocked=len(blocked),
                               blocked=blocked,
                               mode="live" if live else "scripted")


def retrievable_text(store) -> dict[str, str]:
    """Everything ingestion persists that a reader could retrieve, by
    source: the cards, every element text of every L1 model (loaded as
    JSON — the raw file's escaping would hide a needle), and every
    proposal's diff and note. Whitespace-collapsed, lowercased.

    M-27 (P26b-2): the harness used to read cards/*.md only while
    ingestion also writes kb/canonical/ (a figure chunk that mints no
    card lives ONLY there) and kb/proposals/ — the identifier index the
    code gate uses is exactly what this harness exists to double-check,
    so it must look everywhere the gate writes."""
    import json as _json

    def _collapse(parts) -> str:
        # P28: normalized like the scan (NFC, invisible characters
        # stripped) — a name split by a soft hyphen was invisible to the
        # needle check as well as to the pre-P28 scan (found at the
        # adversarial corpus's red-first proof).
        return normalize_text(
            " ".join(" ".join(str(p).split()) for p in parts if p)).lower()

    cards = [p.read_text(encoding="utf-8")
             for p in sorted((store.root / "cards").glob("*.md"))]
    elements = []
    for path in sorted((store.root / "canonical").glob("*.json")):
        model = _json.loads(path.read_text(encoding="utf-8"))
        elements.extend(e.get("text", "") for e in model.get("elements", []))
    proposal_strings = []
    for path in sorted((store.root / "proposals").glob("prop_*.json")):
        proposal = _json.loads(path.read_text(encoding="utf-8"))
        proposal_strings.append(proposal.get("note", ""))
        for change in (proposal.get("diff") or {}).values():
            if isinstance(change, dict):
                proposal_strings.extend(
                    str(v) for v in change.values() if v is not None)
    return {"card": _collapse(cards), "canonical": _collapse(elements),
            "proposal": _collapse(proposal_strings)}
