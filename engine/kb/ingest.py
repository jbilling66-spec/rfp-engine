"""Ingestion: model annotates, code segments and writes (P13/WP13; K1).

The model gets one starved fast-tier call: the code-produced chunk
listing plus the vocabulary below — never card bodies, never a motive.
Segmentation authority is code's (KB1): chunks follow document structure
(engine/kb/chunk.py), ids are content-anchored (engine/kb/identity.py),
and every store write is code's alone. "Ungated" (K1: corpus ingests day
one) means no human approval gate — not model-direct-write.

Pipeline per document (WP13 R1/R2/R7): refuse buyer-authored sources
(S4/T3) → canonical elements + chunks from the raw text → retain the L0
artifact in the restricted store → one model call over the chunk listing
→ identifier index assembly (source_client is ALWAYS in it) →
placeholder substitution over EVERY element → the anonymization scan
gate over the canonical model text AND every card string (block writes
no L1 and no cards, routes to a named human; the L0 artifact stays
behind the access log either way — B59) → persist the L1 model with its
card backrefs → dedup-merge → validated split writes. Out-of-vocabulary
facet values are CLEARED and reported, never silently dropped — v1's
most-repeated failure was a silent facet typo making a card
unretrievable forever.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from engine.extraction.fingerprint import stack_fingerprint
from engine.kb.anonymize import (
    PLACEHOLDER_TYPES,
    apply_placeholders,
    detect_structured,
    merge_identifiers,
    normalize_text,
    scan,
    scan_passed,
)
from engine.kb.canonical import (
    CanonicalDoc,
    Element,
    doc_id_for,
    elements_from_markdown,
    source_hash_for,
    write_model,
)
from engine.kb.chunk import chunk_elements
from engine.kb.identity import identity_block, kb_id_for
from engine.kb.rank import DEDUP_FLOOR, GROUNDING_FLOOR, idf_weights, overlap_score, tokenize
from engine.kb.reconcile import (
    ReconciliationReport,
    match_drifted,
    prior_cards,
    prior_models,
    write_report,
)
from engine.kb.store import KBStore

ROOT = Path(__file__).resolve().parents[2]
_PROMPT_PATH = ROOT / "prompts" / "ingestion_agent" / "prompt.md"
# P28 (P1-4): the second reader — independent lineage, starved to the
# numbered text and the taxonomy; its list is unioned with the first
# reader's before substitution, so both must miss for a residue to
# reach the scan.
REVIEWER_AGENT = "anonymization_reviewer"
_REVIEW_PROMPT_PATH = ROOT / "prompts" / REVIEWER_AGENT / "prompt.md"

# Pre-production facet vocabulary. TODO(spec-gap): vocabulary source of truth — these
# constants serve P2; the retrieval trigger lexicon question (ROADMAP
# backlog: vocabulary scaling is the real cost of a new service line) is
# decided at A2 with the mined corpus (B29(b), B30(c)). type_tags carries
# the v1 atom taxonomy, demoted to metadata (K3).
TYPE_TAGS = frozenset(
    "firm_profile credential partnership product_expertise industry_experience "
    "methodology resource_role accelerator_tool data_migration integration "
    "support_hypercare ocm governance security_compliance commercial_pricing "
    "differentiator proof_case_study proof_reference capability_flag".split()
)
SECTION_TYPES = frozenset(
    "exec_summary methodology staffing timeline pricing_narrative "
    "past_performance references integration_approach data_migration testing "
    "training support_model security_compliance governance company_overview "
    "reporting".split()
)

_OUTCOME_RANK = {"won": 0, "shortlisted": 1, "lost": 2, "unknown": 3, "n/a": 4}

# Every placeholder the taxonomy can mint (P28: derived, never a second list).
_PLACEHOLDER_TOKEN = re.compile(
    "|".join(re.escape(token) for token in PLACEHOLDER_TYPES.values()))


@dataclass
class SourceDoc:
    doc_id: str
    text: str
    source_client: str
    source_pursuit: str
    outcome: str
    date: str
    authored_by: str  # "firm" | "buyer" — only firm-authored ingests (S4/T3)
    known_identifiers: dict[str, str] = field(default_factory=dict)
    # C10/C12: which stack read the source (python-docx primary on this
    # path — B57, affirmed B59). Since P13/C8 the card CARRIES
    # extraction_status (the B51 deferral closed with its readers).
    extractor: str = ""
    extraction_fingerprint: str = ""
    extraction_degraded: bool = False
    media: dict | None = None  # reader facts, e.g. {"images": 1} (C11 flag)
    # P13: the reader's structured elements (canonical producers, C4) and
    # the raw L0 bytes. Absent, they derive from `text` — the markdown
    # parser and utf-8 encoding are the fallbacks, so every existing
    # caller keeps working.
    elements: list | None = None
    source_bytes: bytes | None = None
    # P29a (P1-47): the original filename, retained in the RESTRICTED meta
    # only (behind the access log) — never in a card, a proposal, a run
    # log or a reconciliation record.
    source_name: str | None = None
    # P33b (B153 §3a): the card kind the reader says — a completed
    # response workbook is a past_response. The default keeps every
    # existing caller and the committed store byte-identical.
    doc_kind: str = "section_exemplar"


@dataclass
class IngestReport:
    doc_id: str
    status: str  # "ingested" | "refused" | "blocked"
    cards_written: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    merged: list[dict] = field(default_factory=list)
    cleared_facets: list[dict] = field(default_factory=list)
    findings: list = field(default_factory=list)
    route_to: str | None = None
    extraction_flagged: bool = False  # degraded source: ingested anyway (C10)
    media_flagged: bool = False  # embedded image(s): identity the text scan
    #                              cannot see — surfaced, never blocking (C11)
    reconciliation: dict | None = None  # C9: four-bucket summary on re-ingest
    proposals: list[str] = field(default_factory=list)  # C15: claim promotions
    dry_run: bool = False  # P34a: computed in full, nothing written to the store
    chunk_sizes: list[int] = field(default_factory=list)  # C19: R5 diagnostic
    # P28: the two readers' agreement, as COUNTS only (never values — the
    # run-log rule): first, reviewer, reviewer_only, first_only, structured.
    cross_check: dict = field(default_factory=dict)


def build_annotation_prompt(doc_id: str, chunks, elements) -> str:
    """Render code-produced chunks for the model to ANNOTATE (wire v2:
    segmentation authority moved to code, KB1/C7). The '# DOC:' marker
    leads the prompt so scripted callers key off it deterministically —
    it is prompt scaffolding, never document content."""
    lines = [f"# DOC:{doc_id}", ""]
    for index, chunk in enumerate(chunks):
        path = " / ".join(chunk.doc_path) or "(document preamble)"
        start, end = chunk.elements
        lines.append(f"<<CHUNK {index}: {path}>>")
        lines.append("\n".join(e.text for e in elements[start:end]))
        lines.append("")
    lines.append(f"Allowed section_types: {', '.join(sorted(SECTION_TYPES))}")
    lines.append(f"Allowed type_tags: {', '.join(sorted(TYPE_TAGS))}")
    return "\n".join(lines)


def parse_wire_v2(text: str, doc_id: str,
                  n_chunks: int) -> tuple[dict, list[dict]]:
    """Whitelist the v2 wire: the model annotates chunks it can NUMBER
    but never re-segment. Same discipline as v1 — unknown keys are
    unreachable, out-of-vocabulary facets are cleared and reported,
    unknown identifier types fall to REDACTED. New failure modes are
    loud: an annotation for a chunk that does not exist, or two
    annotations for the same chunk, is wire drift, not data."""
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"{doc_id}: ingestion wire is not valid JSON: {e}") from e

    cleared: list[dict] = []

    def _facets(entry: dict, key: str, vocab: frozenset,
                where: str) -> list[str]:
        kept = []
        for value in entry.get(key, []):
            if value in vocab:
                kept.append(value)
            else:
                cleared.append({"where": where, "facet": key, "value": value})
        return kept

    annotations: dict[int, dict] = {}
    for i, entry in enumerate(raw.get("chunk_annotations", [])):
        if "chunk" not in entry or not isinstance(entry["chunk"], int):
            raise ValueError(
                f"{doc_id}: wire annotation {i} lacks an integer chunk index")
        index = entry["chunk"]
        if not 0 <= index < n_chunks:
            raise ValueError(
                f"{doc_id}: wire annotation {i} names chunk {index}; "
                f"the document has {n_chunks}")
        if index in annotations:
            raise ValueError(
                f"{doc_id}: chunk {index} annotated twice")
        where = f"chunk {index}"
        annotations[index] = {
            "summary": str(entry.get("summary", "")),
            "section_types": _facets(entry, "section_types",
                                     SECTION_TYPES, where),
            "type_tags": _facets(entry, "type_tags", TYPE_TAGS, where),
            "claim_candidates": [
                str(c).strip() for c in entry.get("claim_candidates", [])
                if str(c).strip()
            ],
        }

    qa_pairs = []
    for i, qa in enumerate(raw.get("qa_pairs", [])):
        if "question" not in qa or "answer" not in qa:
            raise ValueError(
                f"{doc_id}: wire qa_pair {i} lacks question/answer")
        qa_pairs.append({"question": str(qa["question"]),
                         "answer": str(qa["answer"])})

    identifiers = _parse_identifiers(raw.get("identifiers", []), cleared,
                                     where="identifiers")

    wire = {
        "annotations": annotations,
        "qa_pairs": qa_pairs,
        "identifiers": identifiers,
        "client_descriptor": str(raw.get("client_descriptor", "")),
    }
    return wire, cleared


def _parse_identifiers(entries, cleared: list[dict], *, where: str) -> dict:
    """value -> type with the whitelist discipline both readers share: an
    empty value is dropped, an unknown type is cleared (reported under
    `where`) and falls to REDACTED — the value is still removed."""
    identifiers = {}
    for ident in entries:
        if not isinstance(ident, dict):
            continue
        value = str(ident.get("value", "")).strip()
        itype = str(ident.get("type", ""))
        if not value:
            continue
        if itype not in PLACEHOLDER_TYPES:
            cleared.append({"where": where, "facet": "type", "value": itype})
            itype = "REDACTED"
        identifiers[value] = itype
    return identifiers


def build_review_prompt(doc_id: str, elements) -> str:
    """The second reader's prompt (P28): the document's element texts,
    numbered, and the identifier types — nothing the first reader saw
    beyond the text itself (no chunking, no vocabulary, no descriptor).
    The '# DOC:' marker leads so scripted callers key off it."""
    lines = [f"# DOC:{doc_id}", ""]
    for index, element in enumerate(elements):
        if element.text:
            lines.append(f"[{index}] {element.text}")
    lines.append("")
    lines.append("Identifier types: " + ", ".join(
        t for t in PLACEHOLDER_TYPES if t != "REDACTED"))
    return "\n".join(lines)


def parse_reviewer_wire(text: str, doc_id: str) -> tuple[dict, list[dict]]:
    """The reviewer's wire: {"identifiers": [{"value", "type"}]} and
    nothing else is read. Not JSON, or no identifiers list, is wire drift
    named after the agent — never an empty review."""
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"{doc_id}: {REVIEWER_AGENT} wire is not valid JSON: {e}") from e
    if not isinstance(raw, dict) or not isinstance(raw.get("identifiers"),
                                                   list):
        raise ValueError(
            f"{doc_id}: {REVIEWER_AGENT} wire lacks an identifiers list")
    cleared: list[dict] = []
    identifiers = _parse_identifiers(raw["identifiers"], cleared,
                                     where="reviewer identifiers")
    return identifiers, cleared


def _clip_summary(summary: str) -> str:
    return "\n".join(summary.splitlines()[:10])


def _placeholders_used(*texts: str) -> list[str]:
    return sorted({m for t in texts for m in _PLACEHOLDER_TOKEN.findall(t)})


_EMPTY_ANNOTATION = {"summary": "", "section_types": [], "type_tags": [],
                     "claim_candidates": []}


def _proposal_note(canonical_doc_id: str, chunk_index: int) -> str:
    """P29a (P1-47): the claim-promotion note names the document by its
    canonical id — composed BEFORE the gate so it is scanned like every
    other persisted string, and written verbatim at step 8."""
    return (f"Claim candidate from {canonical_doc_id} chunk {chunk_index}. "
            "A steward must supply owner and verified_date at acceptance.")


def persisted_texts(model, claim_texts: dict, candidates: list,
                    notes: dict[int, str]) -> dict[str, str]:
    """P29a (P1-47/P1-48): the ONE enumeration of every string the ingest
    persists, keyed by location — the gate scans exactly this set, so a
    new persisted field is added here or it is not written. Elements
    (`<cd>:element:<i>`), claim texts (`claim:<i>:<j>`), each candidate
    card's title/summary/body and question forms (`<kb_id>:form:<n>`),
    and each proposal note (`proposal:note:<i>`)."""
    texts: dict[str, str] = {}
    for i, element in enumerate(model.elements):
        if element.text:
            texts[f"{model.doc_id}:element:{i}"] = element.text
    for (i, j), claim_text in claim_texts.items():
        texts[f"claim:{i}:{j}"] = claim_text
    for cand in candidates:
        kb_id = cand["card"]["kb_id"]
        texts[f"{kb_id}:title"] = cand["card"]["title"]
        texts[f"{kb_id}:summary"] = cand["card"]["summary"]
        texts[f"{kb_id}:body"] = cand["body"]
        for n, form in enumerate(cand["card"].get("question_forms") or ()):
            texts[f"{kb_id}:form:{n}"] = form
    for i, note in notes.items():
        texts[f"proposal:note:{i}"] = note
    return texts


def _card_shell(doc: SourceDoc, kb_id: str, title: str, summary: str,
                doc_kind: str, canonical_doc_id: str,
                identity: dict, *texts: str) -> dict:
    return {
        "kb_id": kb_id,
        "layer": "corpus",
        "doc_kind": doc_kind,
        "title": title,
        "summary": summary,
        "type_tags": [],
        "section_types": [],
        "outcome": doc.outcome,
        "sensitivity": "internal",
        "anonymization": {
            "status": "anonymized",
            "placeholders_used": _placeholders_used(*texts),
        },
        "use_restriction": False,
        "legal_hold": False,
        "canonical_block": False,
        "version": 1,
        "grain": "chunk",
        "canonical_doc_id": canonical_doc_id,
        "content_origin": "source_text",
        "extraction_status": "degraded" if doc.extraction_degraded
        else "clean",
        "identity": identity,
    }


IDENTITY_FIGURE_CLASSES = ("logo", "signature")


def _candidates(doc: SourceDoc, model: CanonicalDoc, wire: dict,
                identifiers: dict[str, str],
                descriptions: dict[int, str] | None = None,
                question_forms: dict[int, list[str]] | None = None,
                ) -> list[dict]:
    """Assemble anonymized card candidates from the (already anonymized)
    canonical model's chunks plus the wire's distilled Q&A, and stamp
    each text chunk's kb_id backref into the model (the descent index).

    `descriptions` (C13) maps figure-chunk index -> the describer's text.
    A described figure mints a card whose content_origin is
    generated_description — labeled at the card level (X10) and
    structurally barred from ever grounding Tier-1 (schema conditional +
    the fact_catalog belt). A logo or signature figure is REMOVED, never
    described (it is client identity, X9); an undescribed figure mints
    nothing. claim_tier_max is deliberately not written (B59's X10
    deviation: zero readers, wrong signal)."""
    descriptions = descriptions or {}
    question_forms = question_forms or {}

    def _anon(text: str) -> str:
        return apply_placeholders(text, identifiers)

    out = []
    for i, chunk in enumerate(model.chunks):
        start, end = chunk.elements
        span = model.elements[start:end]
        if any(e.kind in ("figure", "qa") for e in span):
            figure = next((e for e in span if e.kind == "figure"), None)
            if figure is None:
                continue
            if figure.figure_class in IDENTITY_FIGURE_CLASSES:
                continue  # removed, never described — flag rides 1b
            description = descriptions.get(i)
            if description is None:
                continue
            body = _anon(description)
            kb_id = kb_id_for(body)
            title = (chunk.doc_path[-1] if chunk.doc_path else "Figure")
            card = _card_shell(
                doc, kb_id, title, _clip_summary(body), doc.doc_kind,
                model.doc_id,
                identity_block(body, chunk.doc_path, i, model.source_hash),
                title, body)
            card["content_origin"] = "generated_description"
            if figure.figure_class:
                card["figure_class"] = figure.figure_class
            card["doc_path"] = list(chunk.doc_path)
            out.append({"card": card, "body": body, "chunk_index": i})
            continue
        body = "\n".join(e.text for e in span)
        annotation = wire["annotations"].get(i, _EMPTY_ANNOTATION)
        title = (chunk.doc_path[-1] if chunk.doc_path
                 else (body.splitlines() or ["Untitled"])[0][:80])
        summary = _clip_summary(_anon(annotation["summary"]) or title)
        kb_id = kb_id_for(body)
        card = _card_shell(
            doc, kb_id, title, summary, doc.doc_kind, model.doc_id,
            identity_block(body, chunk.doc_path, i, model.source_hash),
            title, body, summary)
        card["type_tags"] = annotation["type_tags"]
        card["section_types"] = annotation["section_types"]
        forms = question_forms.get(i)
        if forms:
            # P17/C5: anonymized like every other model output, written
            # only when the questioner spoke (writers-omit — the
            # committed corpus stays byte-identical under questioner=None).
            card["question_forms"] = [_anon(q) for q in forms]
            # P29a (P1-48): a form is a persisted string like any other —
            # its placeholders are counted and (below) it is scanned.
            card["anonymization"]["placeholders_used"] = _placeholders_used(
                title, body, summary, *card["question_forms"])
        card["doc_path"] = list(chunk.doc_path)
        card["chunk_span"] = {"chars": chunk.chars, "elements": end - start}
        if chunk.pages:
            card["chunk_span"]["pages"] = list(chunk.pages)
        # chunk_index, not chunk.kb_id: the backref is stamped after
        # reconciliation, which may hand a drifted candidate its PRIOR id.
        out.append({"card": card, "body": body, "chunk_index": i})

    for i, qa in enumerate(wire["qa_pairs"]):
        question, answer = _anon(qa["question"]), _anon(qa["answer"])
        body = f"Q: {question}\n\nA: {answer}"
        kb_id = kb_id_for(body)
        card = _card_shell(
            doc, kb_id, question, _clip_summary(question), "qa_pair",
            model.doc_id,
            identity_block(body, [], i, model.source_hash),
            body)
        out.append({"card": card, "body": body})
    return out


def _survivor_is_candidate(candidate_card: dict, existing_card: dict) -> bool:
    """B15, landed at P13/C12 (B46 item 10 closes at this corrected
    site): OBSERVED SURVIVAL is the first key — a card with a measured
    edit_survival outranks an unmeasured one, and a higher survival
    outranks a lower — then outcome rank (won > shortlisted > lost >
    unknown > n/a), then kb_id lexicographic. Deterministic by
    construction. A fresh candidate never carries a survival, so
    measured content can never be displaced by an unmeasured near-dup;
    the containment override (C8) outranks all of this and transfers
    the measurement instead (see the merge branch)."""
    def rank(card: dict) -> tuple:
        survival = card.get("edit_survival")
        return (0 if survival is not None else 1,
                -(survival if survival is not None else 0.0),
                _OUTCOME_RANK.get(card.get("outcome", "unknown"), 3),
                card["kb_id"])
    return rank(candidate_card) < rank(existing_card)


class _StoreWriter:
    """P34a (B155 §2): every store write of an ingest, behind one object.
    The real run delegates each call to the store; the dry run's twin
    below answers each with nothing — so both runs share ONE control flow
    and the dry report IS the real report, computed without the writes."""

    def __init__(self, store: KBStore):
        self.store = store

    def source(self, doc_id: str, raw: bytes, meta: dict) -> None:
        self.store.restricted.write_source(doc_id, raw, meta)

    def model(self, model) -> None:
        write_model(self.store.root, model)

    def report(self, recon) -> None:
        write_report(self.store.root, recon)

    def card(self, card: dict, body: str, provenance: dict,
             identifiers: dict) -> None:
        self.store.write_card(card, body, provenance, identifiers)

    def rewrite(self, card: dict, body: str) -> None:
        self.store.rewrite_card(card, body)

    def append(self, kb_id: str, provenance: dict, identifiers: dict, *,
               absorbed: str | None = None) -> None:
        self.store.restricted.append_source(kb_id, provenance, identifiers,
                                            absorbed=absorbed)

    def merge(self, src_kb_id: str, dst_kb_id: str) -> None:
        self.store.restricted.merge_into(src_kb_id, dst_kb_id)

    def delete(self, kb_id: str) -> None:
        self.store.delete_card(kb_id)

    def proposal(self, **kw) -> str:
        from engine.flywheel.proposals import ProposalStore
        return ProposalStore(self.store.root).open(**kw)["proposal_id"]


class _DryWriter:
    """The dry run's writer: nothing reaches disk. A proposal's id is the
    deterministic one the real run would mint — same content, same id."""

    def source(self, doc_id: str, raw: bytes, meta: dict) -> None:
        return None

    def model(self, model) -> None:
        return None

    def report(self, recon) -> None:
        return None

    def card(self, card: dict, body: str, provenance: dict,
             identifiers: dict) -> None:
        return None

    def rewrite(self, card: dict, body: str) -> None:
        return None

    def append(self, kb_id: str, provenance: dict, identifiers: dict, *,
               absorbed: str | None = None) -> None:
        return None

    def merge(self, src_kb_id: str, dst_kb_id: str) -> None:
        return None

    def delete(self, kb_id: str) -> None:
        return None

    def proposal(self, **kw) -> str:
        from engine.flywheel.proposals import proposal_id
        return proposal_id(kw["source"], kw["kind"], kw.get("kb_id"),
                           kw.get("diff") or {})


def ingest_document(store: KBStore, caller, log, doc: SourceDoc,
                    *, actor: str = "engine",
                    describer=None, questioner=None,
                    dry_run: bool = False) -> IngestReport:
    """describer (C13, optional): callable(model) -> {chunk_index: text}
    for figure chunks — the vision-caption seam. Pre-A1 there is no live
    vision call (FakeCaller-only), so production passes None and no
    figure card exists yet; the machinery is proven with scripted
    describers and generation lands at A1 (B59).

    questioner (P17/C5, optional — the describer seam's twin, B65
    enrichment step 1): callable(model) -> {chunk_index: [question]},
    the questions each text chunk answers. They land on the card as
    question_forms — FINDABLE (joined into the scored catalog text),
    NEVER QUOTABLE (frontmatter only; the body handed to any drafter
    never contains them — the X10 posture, named test). Production
    passes None pre-A1, so the committed corpus stays unenriched and
    the mapper eval's pinned rates hold (B75§4a); live generation lands
    at the combined UAT/A1 session with the funded re-measure."""
    report = IngestReport(doc_id=doc.doc_id, status="ingested",
                          dry_run=dry_run)
    # P34a (B155 §2): one writer, chosen once; every write below goes
    # through it, so the dry run and the real run share one control flow.
    writer = _DryWriter() if dry_run else _StoreWriter(store)
    written_now: set[str] = set()  # ids this call wrote (or would have)
    deleted_now: set[str] = set()  # ids this call deleted (or would have)

    def exists(kb_id: str) -> bool:
        # The real run: exactly store.card_exists. The dry run: the same
        # answer, mirroring the writes the store never saw — two
        # candidates with one body collide (kb_id_for hashes the body).
        return ((store.card_exists(kb_id) and kb_id not in deleted_now)
                or kb_id in written_now)
    source_bytes = (doc.source_bytes if doc.source_bytes is not None
                    else doc.text.encode("utf-8"))
    # P29a (P1-47): every persisted line names the document by its
    # canonical (content) id — the caller's doc_id is a filename stem at
    # the CLI door and never reaches a firm-store record.
    canonical_id = doc_id_for(source_bytes)

    # 1. Refusal gate: firm-authored sources only (S4/T3).
    if doc.authored_by != "firm":
        log.emit("error", stage="ingestion", error={
            "code": "buyer_authored_source",
            "message": f"{canonical_id}: corpus ingestion accepts firm-authored "
                       "sources only; buyer text never enters the KB (S4/T3)",
            "recoverable": True,
            "action_taken": "surfaced_to_human",
        })
        report.status = "refused"
        return report

    log.emit("stage_start", stage="ingestion")

    # 1b. Degraded extraction still ingests, flagged (the spec's own rule:
    # content is never held back pending better parsing). Media likewise:
    # an embedded logo/signature image carries identity the text scan
    # cannot see — flagged, never blocking. Both ride the report + run
    # log; since P13/C8 the card also carries extraction_status (B51's
    # deferral, closed with its readers).
    media_images = (doc.media or {}).get("images", 0)
    # C13: an identity-class figure (logo/signature) is client identity
    # no text scan can see — flagged like reader-counted images, and
    # never described or minted (X9).
    identity_figures = any(
        getattr(e, "figure_class", None) in IDENTITY_FIGURE_CLASSES
        for e in (doc.elements or ()))
    if doc.extraction_degraded:
        report.extraction_flagged = True
    if media_images or identity_figures:
        report.media_flagged = True
    log.emit("validation", stage="ingestion", validation={
        "check": "extraction",
        "result": "flag" if (doc.extraction_degraded or media_images
                             or identity_figures)
        else "pass",
    })

    # 2. Canonical structure from the raw text — code segments (KB1).
    raw_elements = (doc.elements if doc.elements is not None
                    else elements_from_markdown(doc.text))
    raw_chunks = chunk_elements(raw_elements)
    doc_id = canonical_id
    source_hash = source_hash_for(source_bytes)

    # 2b. Retain the L0 artifact behind the restricted boundary (R2/B59:
    # retention happens whether or not the scan later blocks — the raw
    # artifact sits behind the access log either way, and the audit
    # human adjudicating a block needs the source). Whether THIS content
    # was seen before is captured first — it decides re-ingest below.
    was_seen = store.restricted.source_exists(
        doc_id, actor=actor, purpose="ingest")
    # The merge fold, read once per ingest (P2-46): absorbed id -> owner.
    absorbed = store.restricted.absorbed_owners(actor=actor, purpose="ingest")
    writer.source(doc_id, source_bytes, {
        "doc_id": doc.doc_id, "source_hash": source_hash,
        **({"original_name": doc.source_name} if doc.source_name else {}),
        # C16: the client linkage lives in the RESTRICTED meta so a
        # blocked ingest's retained L0 — which mints no cards and so
        # has no provenance record — is still reachable by its
        # client's purge.
        "source_client": doc.source_client})

    # 3. One starved model call: the chunk listing + vocabulary, never a
    # motive. The model annotates; it cannot re-segment or edit.
    system = _PROMPT_PATH.read_text(encoding="utf-8")
    prompt = build_annotation_prompt(doc.doc_id, raw_chunks, raw_elements)
    result = caller.call("ingestion_agent", tier="fast", prompt=prompt,
                         system=system, stage="ingestion")
    wire, report.cleared_facets = parse_wire_v2(
        result.text, doc.doc_id, len(raw_chunks))

    # 3b. The second reader (P28, P1-4 — the owner's call: a production
    # control on every document). Independent lineage, starved to the
    # numbered text and the taxonomy; it never sees the first reader's
    # list. Its wire is parsed with the same whitelist.
    review = caller.call(REVIEWER_AGENT, tier="fast",
                         prompt=build_review_prompt(doc.doc_id, raw_elements),
                         system=_REVIEW_PROMPT_PATH.read_text(encoding="utf-8"),
                         stage="ingestion")
    reviewed, cleared_by_review = parse_reviewer_wire(review.text, doc.doc_id)
    report.cleared_facets += cleared_by_review

    # 4. Identifier index: code-detected ∪ first reader ∪ second reader ∪
    # metadata-known, later layers taking precedence and the fallback
    # never downgrading a typed entry (P28, B121 §5). Structured
    # identifiers — contact details, URLs, addresses, tax ids, reference
    # numbers — are found by code BEFORE any model's list is trusted, so
    # they are substituted rather than merely blocked. The source client
    # is ALWAYS in it — the scan must not depend on either reader
    # reporting the one identifier we already know.
    structured = detect_structured(
        "\n".join(e.text for e in raw_elements if e.text))
    identifiers = merge_identifiers(structured, wire["identifiers"], reviewed,
                                    doc.known_identifiers)
    identifiers.setdefault(doc.source_client, "CLIENT")
    first = {normalize_text(k).strip() for k in wire["identifiers"]}
    second = {normalize_text(k).strip() for k in reviewed}
    report.cross_check = {
        "first": len(first), "reviewer": len(second),
        "reviewer_only": len(second - first), "first_only": len(first - second),
        "structured": len(structured),
    }

    # 5. Anonymize BETWEEN parse and persist (R7): placeholders over
    # every element, then the model and chunks are rebuilt anonymized —
    # only anonymized text can reach L1 or a card.
    anon_elements = [
        Element(kind=e.kind, text=apply_placeholders(e.text, identifiers),
                level=e.level, page=e.page, figure_class=e.figure_class)
        for e in raw_elements
    ]
    model = CanonicalDoc(
        doc_id=doc_id,
        source_hash=source_hash,
        extractor=doc.extractor or "text",
        extraction_fingerprint=doc.extraction_fingerprint
        or stack_fingerprint("text", {"extractor_version": "stdlib"}),
        extraction_status="degraded" if doc.extraction_degraded
        else "clean",
        media=dict(doc.media or {"images": 0}),
        elements=anon_elements,
        chunks=chunk_elements(anon_elements),
    )

    descriptions = describer(model) if describer is not None else {}
    question_forms = questioner(model) if questioner is not None else {}
    candidates = _candidates(doc, model, wire, identifiers, descriptions,
                             question_forms)

    # 5b. Reconciliation against this document's prior versions (R6/C9).
    # Every prior card lands in exactly one bucket; a drifted candidate
    # takes its prior card's id and history BEFORE anything is written,
    # so ids never rotate and edit_survival never orphans.
    recon = None
    prior_cds = prior_models(store, doc.doc_id, doc_id,
                             actor=actor, purpose="ingest")
    if prior_cds or was_seen:
        lineage = prior_cds + ([doc_id] if was_seen else [])
        recon = ReconciliationReport(doc_id=doc.doc_id,
                                     canonical_doc_id=doc_id,
                                     prior_doc_ids=lineage)
        priors = prior_cards(store, lineage)
        prior_ids = {p["kb_id"] for p, _ in priors}
        # P1-37 (P26b-2): a drifted card keeps its ORIGINAL id by design
        # (ids never rotate), so its filename no longer prefixes its
        # content hash. The id bucket alone re-classified the same
        # unchanged bytes as drifted (0.0) on every later ingest; the
        # content bucket recognises them. Pre-WP13 cards carry no
        # identity block and simply never populate this map.
        prior_by_hash = {
            p["identity"]["content_hash"]: p for p, _ in priors
            if (p.get("identity") or {}).get("content_hash")}
        covered: set[str] = set()
        unmatched_cands = []
        for cand in candidates:
            kb_id = cand["card"]["kb_id"]
            cand_hash = cand["card"]["identity"]["content_hash"]
            if kb_id in prior_ids:
                recon.matched.append(kb_id)
                covered.add(kb_id)
            elif (cand_hash in prior_by_hash
                  and prior_by_hash[cand_hash]["kb_id"] not in covered):
                prior = prior_by_hash[cand_hash]
                cand["card"]["kb_id"] = prior["kb_id"]  # same bytes, kept id
                recon.matched.append(prior["kb_id"])
                covered.add(prior["kb_id"])
            elif store.card_exists(kb_id) or kb_id in absorbed:
                recon.matched.append(kb_id)  # same content, other home
            else:
                unmatched_cands.append(cand)
        unmatched_priors = [(p, b) for p, b in priors
                            if p["kb_id"] not in covered]
        for cand, prior, drift in match_drifted(unmatched_cands,
                                                unmatched_priors):
            card = cand["card"]
            card["kb_id"] = prior["kb_id"]
            card["version"] = int(prior.get("version", 1)) + 1
            # History and steward-set governance carry forward; only the
            # content and its identity facts are new.
            for key in ("edit_survival", "use_restriction", "legal_hold",
                        "canonical_block", "sensitivity", "owner",
                        "verified_date", "review_due"):
                if key in prior:
                    card[key] = prior[key]
            card["identity"]["matched_from"] = prior["kb_id"]
            card["identity"]["drift"] = drift
            cand["drifted"] = True
            covered.add(prior["kb_id"])
            recon.drifted.append({
                "kb_id": prior["kb_id"], "drift": drift,
                "content_hash": card["identity"]["content_hash"]})
        recon.created = [c["card"]["kb_id"] for c in unmatched_cands
                         if not c.get("drifted")]
        recon.orphaned = sorted(prior_ids - covered)
        report.reconciliation = recon.summary()

    # 5c. Backrefs carry the FINAL ids (a drifted chunk points at the
    # prior card it now lives in) — the descent index stays truthful.
    for cand in candidates:
        if "chunk_index" in cand:
            model.chunks[cand["chunk_index"]].kb_id = cand["card"]["kb_id"]

    # 6. The gate: scan EVERY string this ingest will persist — the
    # canonical model text, every card string (question forms included),
    # every claim text and every proposal note — through the one helper
    # that enumerates them (P29a, P1-47/P1-48: a curated list missed the
    # note and the forms; the set is now built from the writers). An
    # identifier surviving in a non-carded element is a block too — L1 is
    # retrievable-adjacent and persists; a proposal file is
    # steward-visible and persists.
    claim_texts: dict[tuple[int, int], str] = {}
    for i in sorted(wire["annotations"]):
        for j, claim in enumerate(wire["annotations"][i]["claim_candidates"]):
            claim_texts[(i, j)] = apply_placeholders(claim, identifiers)
    notes = {i: _proposal_note(model.doc_id, i)
             for (i, _j) in claim_texts}
    report.findings = scan(
        persisted_texts(model, claim_texts, candidates, notes), identifiers)
    if not scan_passed(report.findings):
        report.status = "blocked"
        report.route_to = (store.restricted.humans("audit") or [None])[0]
        log.emit("validation", stage="ingestion", agent="ingestion_agent",
                 validation={"check": "anonymization", "result": "block"})
        log.emit("stage_end", stage="ingestion")
        return report
    log.emit("validation", stage="ingestion", agent="ingestion_agent",
             validation={"check": "anonymization", "result": "pass"})

    # 6b. Persist the L1 model with its kb_id backrefs (the descent
    # index) and the reconciliation report — only after the gate passed.
    writer.model(model)
    # C19 (R5): size is RECORDED, never enforced — the distribution is a
    # diagnostic for extraction findings, and this is where it surfaces.
    report.chunk_sizes = [c.chars for c in model.chunks]
    if recon is not None:
        writer.report(recon)
        # R6 in the trace (C11, enum from C10): drift or orphans flag;
        # an all-matched/created re-ingest passes.
        log.emit("validation", stage="ingestion", validation={
            "check": "reconciliation",
            "result": "flag" if (recon.drifted or recon.orphaned)
            else "pass",
        })

    provenance = {
        "source_pursuit": doc.source_pursuit,
        "source_client": doc.source_client,
        "date": doc.date,
        "ingested_by": "ingestion_agent",
    }

    # 6–7. Dedup-merge against the existing corpus, then write survivors.
    existing = [
        (card, tokenize(f"{card.get('title', '')} {card.get('summary', '')} {body}"))
        for card, body in (store.read_card(c["kb_id"]) for c in store.list_cards())
    ]
    for cand in candidates:
        card, body = cand["card"], cand["body"]

        # Drifted first — the card EXISTS under its prior id by design;
        # its content is replaced in place, its restricted record gains
        # this source, and dedup never sees it (it is already homed).
        if cand.get("drifted"):
            writer.rewrite(card, body)
            writer.append(card["kb_id"], provenance, identifiers)
            continue

        if exists(card["kb_id"]):
            report.skipped.append(card["kb_id"])
            continue

        # Content the store ALREADY absorbed in an earlier merge arrives
        # again with the same content-anchored id — recognize it from the
        # survivor's derived_from fold and append this source rather than
        # re-fighting the merge (idempotent re-ingest, R6).
        owner = absorbed.get(card["kb_id"])
        if owner is not None and exists(owner):
            writer.append(owner, provenance, identifiers)
            report.merged.append({"survivor": owner,
                                  "absorbed": card["kb_id"],
                                  "prior": True})
            continue

        idf = idf_weights([tokens for _, tokens in existing])
        query = tokenize(f"{card['title']} {card['summary']} {body}")
        scored = sorted(
            ((overlap_score(query, tokens, idf, len(existing)), other, tokens)
             for other, tokens in existing),
            key=lambda entry: (-entry[0], entry[1]["kb_id"]),
        )
        returned = [c["kb_id"] for s, c, _ in scored if s >= GROUNDING_FLOOR]
        if scored:
            top_score, top_card, top_tokens = scored[0]
        else:
            top_score, top_card, top_tokens = 0.0, None, []
        log.emit("kb_retrieval", stage="ingestion", agent="ingestion_agent", kb={
            "query": card["title"],
            "step": "card_search",
            "cards_returned": returned,
            "cards_opened": [top_card["kb_id"]] if top_score >= DEDUP_FLOOR else [],
            "cards_cited": [],
            "excluded": [],
            "empty_result": not returned,
        })

        if top_score >= DEDUP_FLOOR:
            # Containment overrides the tie-break (P13/C8 finding): the
            # score is asymmetric — 1.0 means the CANDIDATE's vocabulary
            # is fully carried by the existing card, not that the texts
            # match. When exactly one side contains the other, the
            # CONTAINER survives; letting the fragment win by kb_id
            # deleted the only retrievable home of the container's
            # uncontained content (resp_12's hypercare Q&A, caught by
            # the seed-store diff before commit).
            reverse = overlap_score(top_tokens, query, idf, len(existing))
            if top_score >= 1.0 and reverse < 1.0:
                candidate_survives = False
            elif reverse >= 1.0 and top_score < 1.0:
                candidate_survives = True
            else:
                candidate_survives = _survivor_is_candidate(card, top_card)
            if candidate_survives:
                # A measurement is never discarded (B15/C12): if the
                # absorbed card carried an observed survival and the
                # surviving content has none, the score transfers —
                # same content, same evidence.
                if ("edit_survival" not in card
                        and "edit_survival" in top_card):
                    card["edit_survival"] = top_card["edit_survival"]
                writer.card(card, body, provenance, identifiers)
                writer.merge(top_card["kb_id"], card["kb_id"])
                absorbed[top_card["kb_id"]] = card["kb_id"]
                writer.delete(top_card["kb_id"])
                written_now.add(card["kb_id"])
                deleted_now.add(top_card["kb_id"])
                existing = [(c, t) for c, t in existing
                            if c["kb_id"] != top_card["kb_id"]]
                existing.append((card, query))
                report.cards_written.append(card["kb_id"])
                report.merged.append({"survivor": card["kb_id"],
                                      "absorbed": top_card["kb_id"],
                                      "score": top_score, "kept": "new"})
            else:
                writer.append(top_card["kb_id"], provenance, identifiers,
                              absorbed=card["kb_id"])
                absorbed[card["kb_id"]] = top_card["kb_id"]
                report.merged.append({"survivor": top_card["kb_id"],
                                      "absorbed": card["kb_id"],
                                      "score": top_score, "kept": "existing"})
            continue

        writer.card(card, body, provenance, identifiers)
        written_now.add(card["kb_id"])
        existing.append((card, query))
        report.cards_written.append(card["kb_id"])

    # 8. Claim promotion (C15, the owner's call at B59): every claim
    # candidate becomes a fact-sheet NEW-CARD PROPOSAL — anonymized,
    # scanned above, derived_from-linked to its source chunk card so the
    # purge cascade reaches the atom without the proposal ever naming a
    # client. Nothing becomes a fact card until a steward supplies
    # owner + verified_date at acceptance (S4). Proposal ids are
    # content-deterministic, so a re-ingest re-proposes as a no-op.
    if claim_texts:
        for (i, _j), claim_text in sorted(claim_texts.items()):
            source_card = next(
                (c["card"]["kb_id"] for c in candidates
                 if c.get("chunk_index") == i), None)
            diff = {
                "title": {"after": claim_text.splitlines()[0][:80]},
                "body": {"after": claim_text},
                "layer": {"after": "fact_sheet"},
                "grain": {"after": "atom"},
                "content_origin": {"after": "source_text"},
            }
            if source_card:
                diff["derived_from"] = {"after": [source_card]}
            pid = writer.proposal(
                source={"door": "ingestion",
                        "pursuit_id": doc.source_pursuit},
                target="fact_sheet", kind="new_card",
                at=f"{doc.date}T00:00:00Z", diff=diff,
                note=_proposal_note(model.doc_id, i))  # scanned at step 6
            if pid not in report.proposals:
                report.proposals.append(pid)

    log.emit("stage_end", stage="ingestion")
    return report
