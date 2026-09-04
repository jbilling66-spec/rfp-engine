"""The flywheel's one call site (P26b-2, P1-41; the owner's call: it
runs at accept, synchronously).

Until this module `write_card_signals` and `route_edits` were a library
nothing called: no card ever gained edit_survival, no reviewer edit was
ever routed into the steward inbox, and lesson_to_draft_lag_days could
only be absent. Accept is where a pursuit's edits are final, so accept
is where the engine learns from them:

  1. route this pursuit's unprocessed edit events into proposals
     (the steward decides; nothing self-merges), and append each
     routed event's revised line — same event_id, D30 last-wins;
  2. recompute edit_survival onto every cited card from the WHOLE
     corpus through the resolver's own production filter (B40/D18:
     the writer stores what the resolver reports).

Both writes happen under the KB root's lock (P1-40), inside the pursuit
guard the accept door already holds (the ordering rule in
engine/contracts/locks.py). The accept event is durable before this
runs; a failure here is reported in the response, never an un-accept.
"""

from pathlib import Path


def learn_from_accept(workspace: Path, kb_root: Path, pursuit_id: str, *,
                      at: str) -> dict:
    """-> {"routed": [event_id], "proposals": [proposal_id],
           "signals_written": [kb_id]} — or {"skipped": why}."""
    from engine.contracts import path_lock
    from engine.flywheel.routing import route_edits
    from engine.flywheel.survival import write_card_signals
    from engine.kb.store import KBStore
    from engine.metrics.resolver import Corpus
    from engine.validation.voice import prohibited_terms
    from engine.web.events import EventsLane
    from engine.workspace import PursuitDir

    workspace = Path(workspace)
    kb_root = Path(kb_root)
    if not kb_root.resolve().is_relative_to(workspace.resolve()):
        # Learned signals go onto the workspace's OWN firm KB. A server
        # serving a workspace with no kb/ falls back to the repository's
        # seed store; writing a pilot's survival scores into that would
        # dirty a committed golden. Reported, not silent.
        return {"skipped": f"the KB at {kb_root} is outside the workspace "
                           "— nothing learned onto a shared store"}
    lane = EventsLane(PursuitDir(workspace, pursuit_id))
    store = KBStore(kb_root)
    with path_lock(kb_root):
        revised = route_edits(lane.read(), store, at=at,
                              voice_terms=prohibited_terms())
        for line in revised:
            lane.append_revised(line)
        corpus = Corpus(workspace)
        written = write_card_signals(store, corpus.runs(), corpus.events())
    proposals = sorted({
        line["flywheel_routing"]["action_taken"].split(":", 1)[1]
        for line in revised
        if line["flywheel_routing"]["action_taken"].startswith("proposal:")})
    return {"routed": [line["event_id"] for line in revised],
            "proposals": proposals, "signals_written": written}
