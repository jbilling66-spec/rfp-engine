"""The P17 funded re-measure, READY to run (B75§1a).

P17 changed what the mapper's scorer sees (the pursuit lane joins the
idf universe; question-forms join the catalog text). The committed
corpus is unenriched, so the offline pins hold byte-stable — but the
honest claim "retrieval got BETTER, not just different" needs the
enrichment measured with a real model generating the question-forms.
That spend was REHOMED by the owner to the combined UAT/A1 session (B75§1a);
this module is the harness that session runs, proven offline here with
a scripted questioner (the rebaseline arm's third structural property:
the caller is injected, so the whole arm exercises with zero spend).

Shape: copy the committed corpus to a tmp workspace, enrich each card's
question_forms via the INJECTED questioner (kb_ids preserved — the
frontmatter write never changes identity), re-run the real mapper eval
over the enriched copy, and report every rate against the recorded
baseline INCLUDING the regression direction — a worse number is
reported by name, never absorbed.

The first structural property holds here too: a SCRIPTED run can be
reported (that is how the harness is tested) but never RECORDED as the
measured baseline — record=True under live=False refuses by name.
Recording under a script would be the script's rates wearing the
model's name.
"""

import json
import shutil
from pathlib import Path

from engine.contracts import write_json_atomic

from engine.evals.mapper import evaluate_mapper_set
from engine.kb.store import KBStore

ROOT = Path(__file__).resolve().parents[2]

# The recorded offline baseline — the exact rates the mapper suite pins
# (tests/evals/test_mapper_suite.py::test_measures_are_the_honest_current_numbers
# and the P17 lane-machinery pin in tests/kb/test_lane_search.py).
RECORDED_BASELINE = {
    "recall_at_5": 0.7368,
    "false_gap_rate": 0.0789,
    "true_gap_recall": 0.2917,
}

# Direction of goodness per metric: +1 = higher is better.
_DIRECTION = {"recall_at_5": 1, "false_gap_rate": -1,
              "true_gap_recall": 1}


class RemeasureRefused(RuntimeError):
    """The re-measure result was not recorded, and says why."""


def _enriched_copy(workspace: Path, questioner) -> KBStore:
    """The committed cards, verbatim, plus questioner-generated
    question_forms — ids never change (frontmatter enrichment only)."""
    src = ROOT / "kb" / "cards"
    dst_root = Path(workspace) / "kb"
    if dst_root.exists():
        shutil.rmtree(dst_root)
    shutil.copytree(src, dst_root / "cards")
    store = KBStore(dst_root)
    for card in store.list_cards():
        _, body = store.read_card(card["kb_id"])
        forms = questioner(card, body)
        if forms:
            store.update_card_front(card["kb_id"],
                                    question_forms=list(forms))
    return store


def remeasure_mapper(questioner, *, workspace: Path,
                     live: bool = False, record: bool = False,
                     record_path: Path | None = None) -> dict:
    """Run the enriched-corpus mapper measurement.

    questioner: callable(card, body) -> list[str] — the UAT session
    wraps the live caller here (docs/uat/p17-remeasure.md); the offline
    suite injects a script. record=True writes the result file — refused
    unless live=True (a scripted rate must never wear the model's name).
    """
    if record and not live:
        raise RemeasureRefused(
            "recording a scripted re-measure is refused — the recorded "
            "number would be the script's rates wearing the model's "
            "name (the rebaseline arm's first property)")
    store = _enriched_copy(workspace, questioner)
    measured = evaluate_mapper_set(store=store)
    rates = {k: measured[k] for k in RECORDED_BASELINE}
    delta = {k: round(rates[k] - RECORDED_BASELINE[k], 4)
             for k in RECORDED_BASELINE}
    regressions = sorted(
        k for k, d in delta.items()
        if d * _DIRECTION[k] < 0)
    result = {
        "mode": "live" if live else "scripted",
        "baseline": RECORDED_BASELINE,
        "measured": rates,
        "delta": delta,
        "regressions": regressions,  # reported by name, never absorbed
        "enriched_cards": sum(
            1 for c in store.list_cards() if c.get("question_forms")),
        "recorded": False,
    }
    if record:
        path = Path(record_path or
                    ROOT / "docs" / "uat" / "p17-remeasure-result.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(path, result | {"recorded": True})  # P0-6
        result["recorded"] = True
        result["record_path"] = str(path)
    return result
