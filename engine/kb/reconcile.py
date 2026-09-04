"""Re-ingest reconciliation (C9, WP13 R6).

When a logical document is ingested again — a better OCR pass, a
corrected file, a re-run — its chunks are matched against the cards its
previous version minted, and every card falls into exactly one bucket:

  matched   — same content (content-anchored id already in the store, or
              previously absorbed into a survivor). Nothing moves.
  drifted   — the content changed but is recognizably the same chunk
              (overlap >= MATCH_FLOOR, structural key as tiebreak). The
              card keeps its ORIGINAL id and its history (edit_survival,
              restricted sources); version increments; identity records
              the new content_hash and the drift distance.
  created   — a chunk no prior card covers.
  orphaned  — a prior card no chunk covers. RETAINED, never dropped
              (R6: orphans are reviewed) — curation.orphans_view is the
              steward's queue.

The lineage key is the CALLER's document name: the restricted L0 meta
records {doc_id, source_hash} per content-addressed artifact, so every
prior canonical model of the same logical document is findable without
trusting content similarity for lineage.

The report is persisted clock-free under kb/reconciliation/ (local
evidence, gitignored like kb/runs/) with a content-addressed filename,
so kill/resume rewrites the identical bytes.
"""

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from engine.kb.rank import idf_weights, overlap_score, tokenize
from engine.kb.store import _atomic_write_text

# TODO(spec-gap): MATCH_FLOOR is a strict start per the spec's own
# suggestion (WP13 Consideration 2: "start strict, report drift, tune
# against a real re-ingestion before automating") — the tune rides A1's
# first real re-ingestion. Below the floor, same-position content is a
# create + orphan pair a steward reviews, never a silent merge.
MATCH_FLOOR = 0.7


@dataclass
class ReconciliationReport:
    doc_id: str  # the caller's logical document name
    canonical_doc_id: str  # the NEW L1 model
    prior_doc_ids: list[str] = field(default_factory=list)
    created: list[str] = field(default_factory=list)
    matched: list[str] = field(default_factory=list)
    drifted: list[dict] = field(default_factory=list)  # {kb_id, drift, content_hash}
    orphaned: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        return {
            "created": len(self.created),
            "matched": len(self.matched),
            "drifted": len(self.drifted),
            "orphaned": len(self.orphaned),
        }


def prior_models(store, doc_id: str, current_cd: str, *, actor: str,
                 purpose: str) -> list[str]:
    """Every previous canonical model of this logical document, from the
    restricted L0 meta records — read through the logged door (P2-46:
    this used to reach into the source dir directly)."""
    metas = store.restricted.source_metas(actor=actor, purpose=purpose)
    return sorted(cd for cd, meta in metas.items()
                  if cd != current_cd and meta.get("doc_id") == doc_id)


def prior_cards(store, prior_cd_ids: list[str]) -> list[tuple[dict, str]]:
    """(card, body) for every store card minted from a prior model of
    this document. canonical_doc_id is a public card field — no
    restricted read is needed to walk lineage."""
    wanted = set(prior_cd_ids)
    out = []
    for card in store.list_cards():
        if card.get("canonical_doc_id") in wanted:
            out.append(store.read_card(card["kb_id"]))
    return out


def match_drifted(unmatched_candidates: list[dict],
                  unmatched_priors: list[tuple[dict, str]]) -> list[tuple]:
    """Greedy best-score pairing of leftover candidates to leftover prior
    cards, floor-gated. Returns (candidate, prior_card, drift) triples.
    Structural key equality breaks score ties — the heading path is a
    tiebreak here and nothing more (KB10)."""
    if not unmatched_candidates or not unmatched_priors:
        return []
    prior_tokens = {
        prior["kb_id"]: tokenize(f"{prior.get('title', '')} {body}")
        for prior, body in unmatched_priors
    }
    idf = idf_weights(list(prior_tokens.values()))
    n = len(prior_tokens)
    pairs = []
    for cand in unmatched_candidates:
        cand_tokens = tokenize(f"{cand['card']['title']} {cand['body']}")
        cand_key = cand["card"].get("identity", {}).get("structural_key", "")
        for prior, _body in unmatched_priors:
            forward = overlap_score(
                cand_tokens, prior_tokens[prior["kb_id"]], idf, n)
            backward = overlap_score(
                prior_tokens[prior["kb_id"]], cand_tokens, idf, n)
            score = max(forward, backward)
            if score >= MATCH_FLOOR:
                prior_key = prior.get("identity", {}).get("structural_key", "")
                pairs.append((-score, 0 if cand_key == prior_key else 1,
                              prior["kb_id"], cand["card"]["kb_id"],
                              cand, prior, round(1 - score, 6)))
    pairs.sort(key=lambda p: p[:4])
    taken_cands, taken_priors, out = set(), set(), []
    for _s, _t, prior_id, cand_id, cand, prior, drift in pairs:
        if cand_id in taken_cands or prior_id in taken_priors:
            continue
        taken_cands.add(cand_id)
        taken_priors.add(prior_id)
        out.append((cand, prior, drift))
    return out


def priors_digest(prior_doc_ids: list[str]) -> str:
    """Eight hex characters of the sorted prior set — clock-free and
    machine-independent, like everything else in the name."""
    joined = "\n".join(sorted(prior_doc_ids))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:8]


def report_path(kb_root: Path, report: ReconciliationReport) -> Path:
    """P1-38 (P26b-2): the name is keyed on the PRIOR SET too. The same
    source bytes reconciled against different priors are different
    reconciliations; before this the second erased the first's drift
    record. Same bytes + same priors still overwrite in place."""
    return (Path(kb_root) / "reconciliation"
            / f"{report.doc_id}-{report.canonical_doc_id}"
              f"-{priors_digest(report.prior_doc_ids)}.json")


def write_report(kb_root: Path, report: ReconciliationReport) -> Path:
    path = report_path(kb_root, report)
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(
        path, json.dumps(asdict(report), indent=1, sort_keys=True) + "\n")
    return path
