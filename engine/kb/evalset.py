"""The anonymization eval harness (E4/R13, EVAL_SUITE component row).

Runs every case in a suite file through the REAL ingestion pipeline into a
throwaway store, then checks that no labeled identifier and no
must_not_contain string is retrievable. A case whose ingestion BLOCKED
passes — the gate holding is the desired outcome; leakage is the failure.

The result is a boolean, never a rate (R13): one leaked identifier fails
the suite, and the failure list names the case and the string so a named
human can act on it.

Offline the model is a scripted FakeCaller, so this suite proves the
pipeline and its code gates; the live model's own extraction recall is
measured with the same harness at RFP_LIVE (P8+) by swapping the script
for the real caller. Eval docs never enter a real store (cases are kept
outside the KB so evals measure capability, not memorization).
"""

import importlib
import json
import re
from pathlib import Path

from engine.evals import cases as _shared
from engine.kb.ingest import SourceDoc, ingest_document
from engine.kb.read import read_source
from engine.kb.store import KBStore
from engine.llm import FakeCaller, TracedCaller
from engine.runlog import RunLogger

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


def default_script(meta: dict) -> dict:
    """A competent annotator for ONE document: annotates every chunk the
    engine lists and names the identifiers the harness metadata declares.
    Per-document since the v2 wire (P13/C8) — the annotation prompt is
    built from canonical elements, which deliberately exclude the meta
    comment, so ground-truth identifiers must arrive from outside.
    Deliberately does NOT descriptorize anything — the code post-pass
    must earn the pass."""

    def respond(prompt: str) -> str:
        annotations = [
            {"chunk": int(m.group(1)), "summary": m.group(2).strip(),
             "section_types": [], "type_tags": []}
            for m in _CHUNK_MARKER.finditer(prompt)
        ]
        identifiers = [{"value": meta["client"], "type": "CLIENT"}]
        if meta.get("fee"):
            identifiers.append({"value": meta["fee"], "type": "FEE"})
        for contact in filter(None, (c.strip() for c in
                                     meta.get("contacts", "").split(","))):
            identifiers.append({"value": contact, "type": "REFERENCE_NAME"})
        return json.dumps({
            "chunk_annotations": annotations,
            "qa_pairs": [],
            "identifiers": identifiers,
            "client_descriptor": meta.get("descriptor", "an organization"),
        })

    return {"ingestion_agent": respond}


def evaluate_anonymization_set(cases_path: Path, workdir: Path,
                               script_factory=None, *,
                               caller_factory=None) -> tuple[bool, list[str]]:
    """Boolean over the whole suite + the named failures. Any failure is an
    incident for the audit human, not a trend point.

    script_factory(meta) -> script dict builds the per-document scripted
    model (default_script when omitted) — per-document since the v2 wire,
    see default_script. caller_factory(log) -> TracedCaller swaps the
    scripted FakeCaller for a real one (the RFP_LIVE measurement path);
    omitted, the scripted default stands and the suite spends nothing."""
    cases = _shared.load_cases(Path(cases_path))
    failures: list[str] = []
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
        log = RunLogger(store.root, "run_0001", "kb")
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

        retrievable = " ".join(
            " ".join(p.read_text(encoding="utf-8").split())
            for p in (store.root / "cards").glob("*.md")
        ).lower()
        expected = case.get("expected", {})
        # C11: a document carrying an image must come out media-flagged —
        # a logo or signature is identity the text scan cannot see.
        if (expected.get("media") or {}).get("must_flag") and not report.media_flagged:
            failures.append(
                f"{case['case_id']}: document carries media but the ingest "
                "report is not media-flagged"
            )
        banned = expected.get("labels", []) + expected.get("must_not_contain", [])
        for needle in banned:
            if needle.lower() in retrievable:
                failures.append(
                    f"{case['case_id']}: {needle!r} is retrievable"
                )
    return (not failures), failures
