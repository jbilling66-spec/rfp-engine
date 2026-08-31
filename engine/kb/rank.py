"""Lexical ranking primitives shared by dedup and retrieval. Stdlib only.

Agentic search over the card catalog is the foundation (K4); embeddings are
a later accelerator behind this same seam. The idf table is always built
from the FULL corpus, never a filtered pool — corpus statistics must not
shift with per-query filtering (v1 lesson).

Two floors, deliberately apart: GROUNDING_FLOOR asks "is this ABOUT that
card"; DEDUP_FLOOR asks "is this nearly THAT card". Unseen tokens get the
rarest possible weight, so text full of tokens no card carries scores near
zero even when its domain vocabulary overlaps.

THREE floors now, and the third is why (P11-C9): the first two are on the
`overlap_score` scale, which is NORMALIZED 0-1. `card_search` ranks with
`bm25_score`, which is an UNBOUNDED sum. One constant was serving both
scales, and only the ingestion consumer had it right.
"""

import math
import re
from collections import Counter

DEDUP_FLOOR = 0.5
GROUNDING_FLOOR = 0.35
# bm25 units, NOT overlap units. Same numeric value as GROUNDING_FLOOR, and
# that is inherited rather than calibrated: three runs of the mapper eval
# show no threshold on either scale separates answerable from gap queries
# on this corpus (answerable top-score median 2.087, gap median 1.279, gap
# max 3.517), so any value chosen here would be fitted to 24 cards that A1
# replaces. Splitting the constant is the correctness fix; CHOOSING a
# number is ranker tuning: TODO(spec-gap) deferred to P13/A1 (B41(1)) —
# the marker joined the prose at the pre-P12 audit so this deferral greps
# like every other (B49/F-9).
RETRIEVAL_FLOOR = 0.35
DEFAULT_K = 8

_TOKEN = re.compile(r"[a-z0-9][a-z0-9.%-]*")

_STOPWORDS = frozenset(
    "a an and are as at be by for from has have in is it its of on or that "
    "the this to was we will with our your their you they not can each "
    "which all any been than then there these those into over under about "
    "also".split()
)


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOPWORDS]


def idf_weights(docs: list[list[str]]) -> dict[str, float]:
    """Token -> idf over the given corpus. Callers hold the unseen-token
    default: log((n+1)/0.5), the rarest possible weight."""
    n = len(docs)
    df = Counter(token for doc in docs for token in set(doc))
    return {token: math.log((n + 1) / (count + 0.5)) for token, count in df.items()}


def unseen_idf(n_docs: int) -> float:
    return math.log((n_docs + 1) / 0.5)


def overlap_score(
    query: list[str], doc: list[str], idf: dict[str, float], n_docs: int
) -> float:
    """Rarity-weighted token overlap: Σ idf(matched) / Σ idf(query). The
    dedup and grounding measure — 'how much of the query's rare vocabulary
    does this doc carry'."""
    if not query:
        return 0.0
    default = unseen_idf(n_docs)
    total = sum(idf.get(t, default) for t in query)
    doc_set = set(doc)
    matched = sum(idf.get(t, default) for t in query if t in doc_set)
    return round(matched / total, 6) if total else 0.0


def bm25_score(query: list[str], doc: list[str], idf: dict[str, float]) -> float:
    """BM25-lite for retrieval ranking: Σ idf(t) · tf/(tf+1.2). Unseen query
    tokens contribute nothing here — ranking rewards what a card DOES carry."""
    tf = Counter(doc)
    return round(
        sum(idf.get(t, 0.0) * tf[t] / (tf[t] + 1.2) for t in set(query) if t in tf),
        6,
    )
