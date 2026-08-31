"""The memory-lane bundle (P17/C3, B75§3a).

Three tiers, one search: the firm KB (permanent), the pursuit's own
memory (<pursuit>/memory — retained with the pursuit, purged with it),
and the linked organization's memory (<workspace>/orgs/<org_id>/memory —
firm-authored observations that outlive any one pursuit, B69§2). Lane
awareness is CALL-SITE wiring, never a query kwarg: the bundle is built
where the stage run is configured, so the mapper's bare-query replay
contract (B28(4)) is undisturbed and a firm-only search is byte-identical
to the pre-P17 shape — the `lanes` field never appears on a firm-only
line.

Identity rides the id: firm cards mint kb_…, pursuit cards pkb_…, org
cards okb_… — every cards_returned/opened/cited entry is self-describing
in every existing line, join, and sweep, and store_for() dispatches an
open or descend to the lane that minted the id.

The idf universe is the UNION of the joined catalogs (B75§3b): a lane
join is a different corpus — constant for the pursuit's whole life — not
a per-query filter, so the rank.py corpus-stats law governs facets
exactly as before and `catalog_size` on the line counts the universe the
one idf was computed over.
"""

from dataclasses import dataclass

from engine.kb.store import KBStore

PURSUIT_PREFIX = "pkb_"
ORG_PREFIX = "okb_"


@dataclass(frozen=True)
class Lanes:
    """The joined retrieval universe. firm is always present; pursuit
    joins when the pursuit has memory, org when the frozen brief links
    an organization. org_id must accompany an org lane — the emitted
    line carries it, or the search could not replay from the line."""

    firm: KBStore
    pursuit: KBStore | None = None
    org: KBStore | None = None
    org_id: str | None = None

    def __post_init__(self):
        if self.org is not None and not self.org_id:
            raise ValueError(
                "an org lane requires its org_id — the line must carry "
                "it or the search cannot replay (B75§3a)")

    def stores(self) -> list[tuple[str, KBStore]]:
        out = [("firm", self.firm)]
        if self.pursuit is not None:
            out.append(("pursuit", self.pursuit))
        if self.org is not None:
            out.append(("org", self.org))
        return out

    def joined(self) -> list[str]:
        """Lane names for the log line — empty on firm-only, so the
        field stays off the line and pre-P17 lines replay unchanged."""
        names = [name for name, _ in self.stores()]
        return names if len(names) > 1 else []

    def store_for(self, kb_id: str) -> KBStore:
        """The lane that minted this id — prefix dispatch."""
        if kb_id.startswith(PURSUIT_PREFIX):
            if self.pursuit is None:
                raise KeyError(f"{kb_id}: no pursuit lane in this bundle")
            return self.pursuit
        if kb_id.startswith(ORG_PREFIX):
            if self.org is None:
                raise KeyError(f"{kb_id}: no org lane in this bundle")
            return self.org
        return self.firm


def as_lanes(store) -> Lanes:
    """Accept a bare KBStore (every pre-P17 call site) or a bundle."""
    return store if isinstance(store, Lanes) else Lanes(firm=store)
