"""edit_survival: how much engine-drafted text survived the reviewer.

The north-star metric, and the last of P10's frozen acceptance clauses:
"a heavily-edited section sinks its cited cards' edit_survival."

ONE implementation, two consumers (B40/D18). The resolver derives the
metric fresh from records on every read, and the card writer stores the
same function's answer as a retrieval signal at pursuit accept. They
share this module rather than each computing "survival" their own way,
because a stored signal that disagrees with the reported metric is the
kind of divergence nobody notices until it has been wrong for months.

The math is a proxy and is labelled one: SequenceMatcher's ratio over
whitespace-normalised before/after text. It answers "how much of this
text is still here", not the spec's stricter "unchanged in substance" —
a reviewer rewriting a sentence to say the same thing scores as an edit.
Refining that needs judgement the engine does not have offline; A-phase
owns it. What it does honestly is rank: heavily rewritten sections score
far below lightly touched ones, which is what the retrieval tie-break
consumes.
"""

from difflib import SequenceMatcher

from engine.flywheel.attribution import join


def text_survival(before: str, after: str) -> float:
    """Share of the drafted text still present after the edit.

    Whitespace-normalised so reflowing a paragraph is not an edit. An
    empty `before` yields 1.0: there was nothing to survive, and scoring
    it 0.0 would punish a card for text it never produced.

    `autojunk=False` (P2-45, P26b-2): SequenceMatcher's default treats
    any character appearing in more than 1% of a 200+ character text as
    junk, so past that length the ratio became length- and repetition-
    dependent (one changed word in a 1,550-character section scored
    0.80) and cross-section means compared incomparable numbers. Off,
    the score is the plain matching-ratio at every length."""
    before_norm = " ".join((before or "").split())
    after_norm = " ".join((after or "").split())
    if not before_norm:
        return 1.0
    return round(SequenceMatcher(None, before_norm, after_norm,
                                 autojunk=False).ratio(), 4)


def section_survival(edits: list[dict]) -> float:
    """A section's survival across every edit landed on it. No edits is
    1.0 — the drafted text stood."""
    if not edits:
        return 1.0
    scores = [text_survival(e.get("before", ""), e.get("after", ""))
              for e in edits]
    return round(sum(scores) / len(scores), 4)


def card_survival(records: list[dict], events: list[dict]) -> dict[str, dict]:
    """kb_id -> {survival, observations}.

    A card's value is the mean over every section it fed, so one badly
    rewritten section does not condemn a card that carried five others,
    and a card cited into many rewritten sections sinks further than one
    cited into a single rewrite."""
    per_card: dict[str, list[float]] = {}
    for row in join(records, events):
        score = section_survival(row["edits"])
        for kb_id in row["cards"]:
            per_card.setdefault(kb_id, []).append(score)
    return {kb_id: {"survival": round(sum(scores) / len(scores), 4),
                    "observations": len(scores)}
            for kb_id, scores in sorted(per_card.items())}


def workspace_survival(corpus) -> tuple[float, int] | None:
    """The metric the resolver reports: mean survival weighted by
    observation, with n = the number of section observations. None when
    nothing has been observed — absent, never zero."""
    rows = join(corpus.runs(), corpus.events())
    if not rows:
        return None
    scores = [section_survival(row["edits"]) for row in rows]
    return round(sum(scores) / len(scores), 4), len(scores)


def write_card_signals(store, records: list[dict], events: list[dict],
                       ) -> list[str]:
    """Persist the signal onto the cards it describes (the retrieval
    input KB_DESIGN asks for: "low-survival content sinks in retrieval
    ranking"). Returns the kb_ids written.

    Recomputed from the full record rather than accumulated
    incrementally, so a re-run converges on the same answer instead of
    drifting with how many times it has run."""
    written = []
    for kb_id, signal in card_survival(records, events).items():
        if not store.card_exists(kb_id):
            continue  # a purged or renamed card is not an error here
        store.update_card_front(kb_id, edit_survival=signal["survival"])
        written.append(kb_id)
    return written
