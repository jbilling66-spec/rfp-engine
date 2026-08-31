"""The KB Mapper component suite (B40/D8) and the frozen acceptance
clause "broken mapper prompt fails only its component eval".

The mapper has NO prompt — B28 made it pure code — so the clause reads
against its tunable surface: the grounding floor and the verdict rule
that card_search + confidence.verdict apply. Perturbing that surface
must move THIS lane's numbers and leave every sibling lane's numbers
byte-identical; that is what "regressions localize" means operationally.
"""

import json

import pytest

from pathlib import Path

from engine.evals.mapper import CASES_PATH, evaluate_mapper_set
from engine.evals.run import anonymization_lane, injection_lane, mapper_lane

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def report():
    return evaluate_mapper_set()


def test_the_suite_is_labeled_data_not_generated_output():
    """Fixture integrity: the cases are hand-authored against the
    committed corpus, and every labeled card really exists in it — a
    label naming a card the store lacks would make recall unmeasurable
    while still printing a number."""
    from pathlib import Path

    from engine.evals.cases import load_cases
    from engine.evals.mapper import ROOT
    from engine.kb.store import KBStore

    cases = load_cases(CASES_PATH)
    known = {c["kb_id"] for c in KBStore(ROOT / "kb").list_cards()}
    labeled = {kb_id for case in cases
               for kb_id in case["expected"]["labels"]}
    assert labeled, "an answerable suite must label cards"
    assert labeled <= known
    assert len(cases) == 100
    held_out = sum(1 for c in cases if c["held_out"])
    assert held_out / len(cases) >= 0.20, "E6: keep >=20% permanently held out"


def test_gap_cases_are_genuinely_absent_from_the_corpus():
    """The absence twin: a true-gap case whose topic IS in the corpus
    would make true_gap_recall meaningless. Each gap case's labels are
    empty AND its must_flag is set — the two halves of "no card should
    answer this"."""
    from engine.evals.cases import load_cases

    gaps = [c for c in load_cases(CASES_PATH) if c["expected"]["must_flag"]]
    assert len(gaps) == 24
    assert all(c["expected"]["labels"] == [] for c in gaps)


def test_measures_are_the_honest_current_numbers(report):
    """Records what the mapper actually does today, so a change to
    retrieval cannot pass unnoticed. These are NOT passing numbers:
    recall@5 0.7368 misses its 0.90 bar and false_gap_rate 0.0789 misses
    its 0.05 ceiling (P10-F10, routed to the owner — a ranker change ripples
    through every plan and golden). If a commit moves these, it moved
    retrieval: re-derive deliberately and say so."""
    assert report["n_cases"] == 100
    assert report["n_answerable"] == 76
    assert report["n_gap_cases"] == 24
    assert report["recall_at_5"] == 0.7368
    assert report["false_gap_rate"] == 0.0789
    assert report["true_gap_recall"] == 0.2917
    # 24 -> 23 at P13/C8: resp_12's two distilled QA cards folded into
    # their annotated Q&A-section chunk (containment dedup). Every rate
    # above is unchanged — the canonical rebuild moved no measure.
    assert report["searchable_cards"] == 23


def test_the_suite_is_not_green_by_construction(report):
    """A suite that cannot fail proves nothing (the injection-suite
    property, B34(18)): every rate must be strictly inside its bounds."""
    for metric in ("recall_at_5", "true_gap_recall"):
        assert 0.0 < report[metric] < 1.0
    assert 0.0 < report["false_gap_rate"] < 1.0


def test_broken_tunable_surface_fails_only_mapper_lane(monkeypatch):
    """THE acceptance clause. Perturb the mapper's grounding floor — its
    tunable surface, the analogue of a prompt for a code-only agent —
    and the mapper lane's numbers move while its siblings' stay
    byte-identical."""
    clean_mapper = mapper_lane()
    clean_siblings = {"injection": injection_lane(),
                      "anonymization": anonymization_lane()}

    import engine.planning.confidence as confidence

    # RETRIEVAL_FLOOR since P11-C9: the bm25-scale floor the verdict reads.
    # Patched on `confidence` because verdict() resolves it as a module
    # global at call time; mapper.py binds the VALUE at import, so it keeps
    # its own copy — which is exactly why the two must be patched at the
    # attribute each site actually reads (see test_the_two_floors_are_independent).
    monkeypatch.setattr(confidence, "RETRIEVAL_FLOOR", 10.0)
    broken_mapper = mapper_lane()
    broken_siblings = {"injection": injection_lane(),
                       "anonymization": anonymization_lane()}

    # The regression lands in the mapper lane...
    assert broken_mapper["measures"] != clean_mapper["measures"]
    assert (broken_mapper["measures"]["false_gap_rate"]
            > clean_mapper["measures"]["false_gap_rate"])
    # ...and nowhere else.
    assert json.dumps(broken_siblings, sort_keys=True) == json.dumps(
        clean_siblings, sort_keys=True)


def test_unbroken_twin_reproduces(report):
    """The other direction: with nothing perturbed the suite is
    deterministic, so a moved number always means moved code or data."""
    assert evaluate_mapper_set() == report


def test_a_ceiling_bar_reads_as_a_ceiling():
    """false_gap_rate_max is a ceiling: the suffix carries the direction
    so a record can never hide which way a bar points."""
    from engine.evals.release import score_suites

    suites, failures = score_suites({"mapper": {
        "basis": "deterministic", "blocking": True,
        "bar": {"false_gap_rate_max": 0.05},
        "measures": {"false_gap_rate": 0.2}}})
    assert failures == ["mapper.false_gap_rate"]
    suites, failures = score_suites({"mapper": {
        "basis": "deterministic", "blocking": True,
        "bar": {"false_gap_rate_max": 0.05},
        "measures": {"false_gap_rate": 0.01}}})
    assert failures == []
    assert suites["mapper"]["status"] == "pass"


# ------------------------------------------ the floor split (P11-C9, B48)

def test_thin_content_never_fires_on_this_corpus_and_the_branch_is_still_live():
    """P11-C9. `GROUNDING_FLOOR` is documented and calibrated for
    `overlap_score` (normalized 0-1); `card_search` ranks with
    `bm25_score` (unbounded, measured 0.0686-6.7143). Applying one to the
    other made `thin_content` unreachable: `verdict` needs EVERY returned
    card below the floor, and search returns up to 8.

    So the three-way verdict silently collapsed to "did search return
    anything at all", and both mapper gap metrics have been measuring
    EMPTINESS rather than confidence. That identity is pinned below.

    Non-vacuity is the point: the branch is proven reachable by raising
    the floor, so this is a measured property of the corpus, not dead
    code being asserted away."""
    import engine.planning.confidence as conf
    from engine.kb.retrieve import card_search
    from engine.kb.store import KBStore
    from engine.evals.cases import load_cases
    from engine.evals.mapper import CASES_PATH

    class _Sink:
        def __getattr__(self, _):
            return lambda *a, **k: None

    store = KBStore(ROOT / "kb")
    cases = load_cases(CASES_PATH)
    scored = []
    for case in cases:
        res = card_search(store, case["input"]["prompt_context"],
                          log=_Sink(), stage="eval", agent="kb_mapper")
        scored.append(([r.score for r in res.results],
                       case["expected"]["must_flag"]))

    calls = [conf.verdict(s) for s, _ in scored]
    assert calls.count("thin_content") == 0
    assert calls.count("no_content") == 13
    assert calls.count("grounded") == 87

    # ...and the collapse is exact: a "gap" verdict IS an empty result set.
    empty_answerable = sum(1 for s, flag in scored if not flag and not s)
    empty_gap = sum(1 for s, flag in scored if flag and not s)
    assert empty_answerable == 6 and empty_gap == 7, (
        "false_gap_rate 6/76 and true_gap_recall 7/24 are exactly the "
        "queries that returned nothing — the floor never discriminated")

    # The branch is live code: raise the floor and it fires.
    original = conf.RETRIEVAL_FLOOR
    try:
        conf.RETRIEVAL_FLOOR = 1.2
        raised = [conf.verdict(s) for s, _ in scored]
    finally:
        conf.RETRIEVAL_FLOOR = original
    assert raised.count("thin_content") > 0, \
        "thin_content is unreachable at ANY floor — then it is dead code"


def test_the_two_floors_are_independent():
    """The defect was one constant serving two scales. `ingest.py` pairs
    GROUNDING_FLOOR with `overlap_score`, which is the calibrated and
    CORRECT pairing — so retuning retrieval must not move the ingestion
    trace, and vice versa.

    Patching is done at the attribute each site actually reads: both
    consumers use `from … import`, which binds the VALUE at import, so
    patching the source module would reach neither."""
    import engine.kb.ingest as ingest_mod
    import engine.kb.rank as rank_mod
    import engine.planning.confidence as conf

    assert rank_mod.RETRIEVAL_FLOOR == rank_mod.GROUNDING_FLOOR == 0.35, \
        "the split preserved the VALUE — only the scales were separated"

    # Exactly one consumer of the overlap-scale floor survives.
    import inspect
    planning = inspect.getsource(conf) + inspect.getsource(
        __import__("engine.planning.mapper", fromlist=["x"]))
    assert "GROUNDING_FLOOR" not in planning.replace(
        "GROUNDING_FLOOR is documented", "").replace(
        "Reads RETRIEVAL_FLOOR, not GROUNDING_FLOOR", ""), \
        "a bm25-scale site still reads the overlap-scale floor"

    # Moving the ingestion floor cannot move the mapper lane.
    clean = mapper_lane()
    before = ingest_mod.GROUNDING_FLOOR
    try:
        ingest_mod.GROUNDING_FLOOR = 0.99
        assert json.dumps(mapper_lane(), sort_keys=True) == json.dumps(
            clean, sort_keys=True), \
            "the ingestion floor reached the mapper — still coupled"
    finally:
        ingest_mod.GROUNDING_FLOOR = before


# ------------------------------------------------ bar discipline (P11-C10)

def test_a_case_level_bar_may_not_name_a_metric_the_lane_does_not_bar():
    """The 24 gap cases carried `bar: 0.8` for `true_gap_recall` — a
    number the owner has explicitly NOT set (run.py:23-28 says so). Nothing
    read it, so it changed no result; it was a second, contradictory
    record of an unset control, which is how a metric ends up with two
    answers and no owner.

    Stripped, and the invariant asserted: a case-level bar must name a
    metric the lane bars, and agree with it."""
    import json as _json
    from pathlib import Path

    from engine.evals.run import MAPPER_BAR

    cases = _json.loads(
        Path(CASES_PATH).read_text(encoding="utf-8"))
    checked = 0
    for case in cases:
        scoring = case.get("scoring", {})
        if "bar" not in scoring:
            continue
        metric = scoring["metric"]
        assert metric in MAPPER_BAR, (
            f"{case['case_id']} carries a bar for {metric!r}, which the "
            f"lane does not bar — a phantom control")
        assert scoring["bar"] == MAPPER_BAR[metric], (
            f"{case['case_id']}: case bar {scoring['bar']} disagrees with "
            f"the lane's {MAPPER_BAR[metric]}")
        checked += 1
    assert checked == 76, "the lane-backed bars must still be there"

    # true_gap_recall remains measured and reported, bar-less, pending J11.
    assert "true_gap_recall" not in MAPPER_BAR
    assert any(c.get("scoring", {}).get("metric") == "true_gap_recall"
               and "bar" not in c["scoring"] for c in cases)


def test_mapper_bars_are_recorded_not_blocking():
    """B41(1): recorded-not-blocking means FAILS AND IS NAMED but does not
    gate — not "silently passes". The last pair of assertions is the
    teeth."""
    from engine.evals.release import score_suites
    from engine.evals.run import MAPPER_BAR

    assert MAPPER_BAR == {"recall_at_5": 0.90, "false_gap_rate_max": 0.05}

    lane = mapper_lane()
    assert lane["blocking"] is False
    assert "status" not in lane, "lanes never grade themselves"
    assert lane["measures"]["missed_cases"] and lane["measures"][
        "false_gap_cases"], "the misses stay named on the record"
    assert "true_gap_recall" in lane["measures"], \
        "measured and reported bar-less, pending J11"

    suites, failures = score_suites({"mapper": lane})
    assert suites["mapper"]["status"] == "fail"
    assert failures == [], "recorded-not-blocking must not gate promotion"

    # The blocking twin DOES gate — proving the above is a property of the
    # flag, not of the numbers happening to pass.
    suites2, failures2 = score_suites({"mapper": dict(lane, blocking=True)})
    assert suites2["mapper"]["status"] == "fail"
    assert failures2, "a blocking lane with the same numbers must gate"


def test_no_bar_value_moved_this_phase():
    """P11's frozen row: "no bar VALUE moves in either direction".

    The pinned NAMES are derived by introspection, so a new lane arriving
    with a new bar fails here until someone pins it deliberately — the
    gap that let MAPPER_BAR go unpinned while poison and extraction were
    covered."""
    import engine.evals.run as run_mod

    pinned = {
        "POISON_BAR": {"recall": 0.98, "precision": 0.85},
        "EXTRACTION_BAR": {"claim_extraction_recall": 0.98,
                           "claim_over_extraction_rate_max": 0.15},
        "INJECTION_BAR": {"family_floor": 0.75, "benign_false_positives": 0},
        "ANONYMIZATION_BAR": {"recall": 1.0},
        "MAPPER_BAR": {"recall_at_5": 0.90, "false_gap_rate_max": 0.05},
        "CONSISTENCY_BAR": {"code_detection_rate": 1.0},
        "INTAKE_BAR": {"weight_recall": 0.95, "target_coverage": 1.0},
        "STRUCTURE_BAR": {"exact_match": 1.0},
        "TRAJECTORY_BAR": {"pass_rate": 1.0},
        "VOICE_BAR": {"recall": 1.0, "false_positive_count_max": 0},
    }
    live = {n for n in dir(run_mod)
            if n.endswith("_BAR") and isinstance(getattr(run_mod, n), dict)}
    assert live == set(pinned), (
        f"a bar constant appeared or vanished: {live ^ set(pinned)} — pin it "
        "here deliberately, which is the point")
    for name, value in pinned.items():
        assert getattr(run_mod, name) == value, f"{name} MOVED"
