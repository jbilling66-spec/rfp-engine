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

P2-37 (P26b-3): "live" is no longer a keyword the caller declares about
itself. live=True is accepted only when RFP_LIVE=1 is set (the same gate
the live caller's constructor honours, B30(e)) AND the questioner was
built by `live_questioner` over a TracedCaller wrapping a LiveCaller —
a bare callable under live=True is refused naming the door. And the
recorded baseline is no longer a hand-typed copy: `recorded_baseline()`
reads `evals/mapper/recorded.json` — written only by
`engine.evals.mapper.write_recorded` from a live recompute and
drift-tested against one — so the three numbers have one source, and
that source ships (the release record under docs/releases/ does not).
"""

import json
import shutil
from pathlib import Path

from engine.contracts import write_json_atomic

from engine.evals.mapper import evaluate_mapper_set
from engine.kb.store import KBStore

ROOT = Path(__file__).resolve().parents[2]

# The three rates the re-measure compares, and the direction of goodness
# per metric: +1 = higher is better.
_DIRECTION = {"recall_at_5": 1, "false_gap_rate": -1,
              "true_gap_recall": 1}

QUESTIONER_AGENT = "questioner"
QUESTIONER_TIER = "mid"


class RemeasureRefused(RuntimeError):
    """The re-measure result was not recorded, and says why."""


def recorded_baseline() -> dict:
    """The three rates from `evals/mapper/recorded.json` — the recorded
    mapper report, re-derived only by `mapper.write_recorded` and
    drift-tested against a live recompute (the offline pins in
    tests/evals/test_mapper_suite.py carry the same literals, so a moved
    number reds there first)."""
    from engine.evals.mapper import RECORDED_PATH

    if not RECORDED_PATH.exists():
        raise RemeasureRefused(
            f"no recorded mapper report at {RECORDED_PATH} — re-derive it "
            "with engine.evals.mapper.write_recorded before re-measuring")
    recorded = json.loads(RECORDED_PATH.read_text(encoding="utf-8"))
    return {key: recorded[key] for key in _DIRECTION}


def live_questioner(caller):
    """The questioner the UAT session runs (docs/uat/p17-remeasure.md):
    one call per card, forms only, never prose. Built ONLY over a
    TracedCaller wrapping a LiveCaller — an untraced live call must not
    exist, and a scripted caller must never wear the live name."""
    from engine.llm.caller import TracedCaller
    from engine.llm.live import LiveCaller

    if not isinstance(caller, TracedCaller) or not isinstance(
            caller.caller, LiveCaller):
        raise RemeasureRefused(
            "live_questioner needs a TracedCaller wrapping a LiveCaller — "
            f"got {type(caller).__name__}; a scripted or untraced caller "
            "cannot produce a live re-measure")

    def questioner(card, body) -> list[str]:
        prompt = ("List 3 short questions this knowledge-base entry "
                  "answers, one per line, no numbering:\n\n"
                  f"TITLE: {card.get('title', '')}\n{body[:2000]}")
        result = caller.call(QUESTIONER_AGENT, tier=QUESTIONER_TIER,
                             prompt=prompt)
        return [line.strip() for line in result.text.splitlines()
                if line.strip()][:3]

    questioner.live = True
    return questioner


def _refuse_unless_live(questioner) -> None:
    from engine.llm.caller import live_allowed

    if not live_allowed():
        raise RemeasureRefused(
            "live=True refused: RFP_LIVE=1 is not set — the same gate the "
            "live caller's constructor honours (B30(e)); nothing was "
            "measured under the live name")
    if not getattr(questioner, "live", False):
        raise RemeasureRefused(
            "live=True refused: the questioner was not built by "
            "live_questioner over a TracedCaller wrapping a LiveCaller — "
            "a bare callable cannot declare itself live (P2-37)")


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
    builds it with live_questioner (docs/uat/p17-remeasure.md); the
    offline suite injects a script. record=True writes the result file —
    refused unless live=True (a scripted rate must never wear the
    model's name), and live=True is itself refused unless RFP_LIVE=1 is
    set and the questioner is the live one (P2-37).
    """
    if record and not live:
        raise RemeasureRefused(
            "recording a scripted re-measure is refused — the recorded "
            "number would be the script's rates wearing the model's "
            "name (the rebaseline arm's first property)")
    if live:
        _refuse_unless_live(questioner)
    baseline = recorded_baseline()
    store = _enriched_copy(workspace, questioner)
    measured = evaluate_mapper_set(store=store)
    rates = {k: measured[k] for k in baseline}
    delta = {k: round(rates[k] - baseline[k], 4) for k in baseline}
    regressions = sorted(
        k for k, d in delta.items()
        if d * _DIRECTION[k] < 0)
    result = {
        "mode": "live" if live else "scripted",
        "baseline": baseline,
        "measured": rates,
        "delta": delta,
        "regressions": regressions,  # reported by name, never absorbed
        "enriched_cards": sum(
            1 for c in store.list_cards() if c.get("question_forms")),
        "recorded": False,
    }
    if record:
        result.update(record_result(result, record_path))
    return result


def record_result(result: dict, record_path: Path | None = None) -> dict:
    """Write a re-measure result as the record — only a LIVE result; the
    writer checks the mode it is handed rather than trusting the caller."""
    if result.get("mode") != "live":
        raise RemeasureRefused(
            "only a live result is recorded — this one is "
            f"{result.get('mode')!r}")
    path = Path(record_path or
                ROOT / "docs" / "uat" / "p17-remeasure-result.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(path, result | {"recorded": True})  # P0-6
    return {"recorded": True, "record_path": str(path)}
