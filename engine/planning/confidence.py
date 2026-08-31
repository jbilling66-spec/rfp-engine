"""Score -> confidence mapping and the grounding verdict.

ONE floor per SCALE, one source: engine.kb.rank.RETRIEVAL_FLOOR — a
deliberate divergence from v1's separate planning floor (0.25); two
floors for "is this about that card" on the same scale would drift (B28).

Reads RETRIEVAL_FLOOR, not GROUNDING_FLOOR (P11-C9). The scores arriving
here come from `card_search`, i.e. `bm25_score`, which is unbounded.
GROUNDING_FLOOR is documented and calibrated for `overlap_score`, which
is normalized 0-1, and its one correct consumer is the ingestion dedup
trace. Applying an overlap-scale threshold to bm25 output is what made
`thin_content` unreachable: measured over all 100 mapper eval cases it
fires ZERO times, because `verdict` needs EVERY returned card below the
floor and search returns up to 8. The verdict silently collapsed from
three-way to "did search return anything at all", so `false_gap_rate` and
`true_gap_recall` were both measuring emptiness rather than confidence.

The VALUE is unchanged, deliberately — see rank.py. Splitting the
constant is the correctness fix; choosing a new number is ranker tuning
and is deferred to P13/A1 with the corpus that replaces this one.

confidence(score) = score / (score + 1) — monotone, bounded to (0, 1),
corpus-statistics-free, so the plan's 0..1 confidence field never
depends on idf tables that shift with the corpus.
"""

from engine.kb.rank import RETRIEVAL_FLOOR

__all__ = ["RETRIEVAL_FLOOR", "confidence", "verdict"]


def confidence(score: float) -> float:
    return round(score / (score + 1.0), 3)


def verdict(scores: list[float]) -> str:
    """The mapper's honesty rule: no results -> no_content; results but
    none at the floor -> thin_content; otherwise grounded."""
    if not scores:
        return "no_content"
    if all(s < RETRIEVAL_FLOOR for s in scores):
        return "thin_content"
    return "grounded"
