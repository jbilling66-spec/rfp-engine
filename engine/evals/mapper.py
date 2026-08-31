"""The KB Mapper component suite (EVAL_SUITE Tier-1 row; B40/D8).

Deterministic — the mapper makes NO model call (B28 made it pure code),
so these numbers are real offline and reproducible from the repo alone.
What the suite exercises is the mapper's two moving parts, the same
functions map_sections calls: card_search for retrieval and
confidence.verdict for the grounding decision. That pair IS the "prompt"
the frozen acceptance clause names — the mapper's tunable surface — and
perturbing it must fail this lane and no other.

Three measures, and the third exists because the first two are gameable:
  recall_at_5     — of answerable cases, the labeled card in the top 5.
  false_gap_rate  — answerable cases the mapper called empty (E3's bar).
  true_gap_recall — gap cases it correctly refused to ground.
A mapper that grounds everything scores false_gap_rate 0.0 and would pass
a one-sided bar while silently disabling the invention guard; a mapper
that gaps everything scores true_gap_recall 1.0. Only the pair is honest
(the v1 metric-contract lesson: a rate that collapses two outcomes lies,
and a monitor with no bar is a control nobody built).

Corpus caveat, stated because the number would otherwise flatter us:
card_search excludes fact_sheet cards from the searchable universe by
design (B34(26)), so recall@5 here runs over 24 corpus cards. This
measures paraphrase robustness, not retrieval breadth; the breadth
measure needs a real KB and arrives at A1.
"""

from pathlib import Path

from engine.evals.cases import load_cases

ROOT = Path(__file__).resolve().parents[2]
CASES_PATH = ROOT / "evals" / "mapper" / "cases.json"
RECALL_K = 5


def _searchable_card_count(store) -> int:
    return sum(1 for c in store.list_cards()
               if c.get("layer") != "fact_sheet" and not c.get("use_restriction"))


def evaluate_mapper_set(path: Path = CASES_PATH, *, store=None) -> dict:
    """Run every case through the REAL retrieval + verdict path. The log
    is a sink: card_search emits a kb_retrieval line per query and the
    suite has no run to attach them to (eval runs are not pursuits)."""
    from engine.kb import card_search
    from engine.kb.store import KBStore
    from engine.planning.confidence import verdict

    class _Sink:
        def emit(self, *args, **kwargs):
            return 0

    store = store if store is not None else KBStore(ROOT / "kb")
    cases = load_cases(path)
    log = _Sink()

    hits = misses = false_gaps = 0
    true_gap_caught = 0
    answerable = gap_cases = 0
    missed_ids: list[str] = []
    false_gap_ids: list[str] = []
    grounded_gap_ids: list[str] = []

    for case in cases:
        query = case["input"]["prompt_context"]
        result = card_search(store, query, log=log, stage="eval",
                             agent="kb_mapper")
        returned = [r.kb_id for r in result.results]
        scores = [r.score for r in result.results]
        grounded = verdict(scores) == "grounded"

        if case["expected"]["must_flag"]:
            gap_cases += 1
            if grounded:
                grounded_gap_ids.append(case["case_id"])
            else:
                true_gap_caught += 1
            continue

        answerable += 1
        labels = set(case["expected"]["labels"])
        if labels & set(returned[:RECALL_K]):
            hits += 1
        else:
            misses += 1
            missed_ids.append(case["case_id"])
        if not grounded:
            false_gaps += 1
            false_gap_ids.append(case["case_id"])

    return {
        "suite": "mapper_retrieval",
        "n_cases": len(cases),
        "n_answerable": answerable,
        "n_gap_cases": gap_cases,
        "recall_at_5": round(hits / answerable, 4) if answerable else 1.0,
        "false_gap_rate": (round(false_gaps / answerable, 4)
                           if answerable else 0.0),
        "true_gap_recall": (round(true_gap_caught / gap_cases, 4)
                            if gap_cases else 1.0),
        "searchable_cards": _searchable_card_count(store),
        "missed_cases": sorted(missed_ids),
        "false_gap_cases": sorted(false_gap_ids),
        "grounded_gap_cases": sorted(grounded_gap_ids),
    }
