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

from engine.evals.cases import load_cases, rate, write_report

ROOT = Path(__file__).resolve().parents[2]
CASES_PATH = ROOT / "evals" / "mapper" / "cases.json"
# P2-37 (P26b-3): the recorded mapper numbers, the voice/injection
# pattern — re-derived only by write_recorded, drift-tested against a
# live recompute, and SHIPPED (the release record under docs/releases/
# is deny-listed from the public mirror, so nothing that runs there may
# read it; the dry-run cut caught the first design).
RECORDED_PATH = ROOT / "evals" / "mapper" / "recorded.json"
RECALL_K = 5

# P2-36 (P26b-3): floors are the committed counts (76 answerable, 24 gap
# cases); a shrink is a bar edit with a B-entry.
MINIMUM_N = {"answerable": 76, "gap_cases": 24}


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
        "recall_at_5": rate(hits, answerable, floor=MINIMUM_N["answerable"],
                            lane="mapper", of="answerable cases"),
        "false_gap_rate": rate(false_gaps, answerable,
                               floor=MINIMUM_N["answerable"],
                               lane="mapper", of="answerable cases"),
        "true_gap_recall": rate(true_gap_caught, gap_cases,
                                floor=MINIMUM_N["gap_cases"],
                                lane="mapper", of="gap cases"),
        "minimum_n": dict(MINIMUM_N),
        "searchable_cards": _searchable_card_count(store),
        "missed_cases": sorted(missed_ids),
        "false_gap_cases": sorted(false_gap_ids),
        "grounded_gap_cases": sorted(grounded_gap_ids),
    }


def write_recorded(path: Path = RECORDED_PATH) -> Path:
    """Re-derive the recorded mapper numbers CONSCIOUSLY (the drift test
    names this call): `python -c "from engine.evals.mapper import
    write_recorded; write_recorded()"`."""
    return write_report(evaluate_mapper_set(), path)
