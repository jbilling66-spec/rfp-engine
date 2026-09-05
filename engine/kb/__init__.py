"""Knowledge base: three-layer card store, restricted provenance, retrieval.

Grows through P2 commit by commit; consumers import from this package, not
the submodules.
"""

from engine.kb.anonymize import apply_placeholders, scan, scan_passed
from engine.kb.evalset import evaluate_anonymization_set
from engine.kb.manifest import Manifest, ManifestError, load_manifest
from engine.kb.ingest import IngestReport, SourceDoc, ingest_document
from engine.kb.lanes import Lanes, as_lanes
from engine.kb.provenance import ProvenanceAccessDenied, RestrictedStore
from engine.kb.purge import (
    PurgeReport,
    post_purge_sweep,
    purge_client,
    purge_org,
    purge_pursuit_memory,
)
from engine.kb.retrieve import (
    SearchResult,
    DeprecatedCard,
    UseRestrictedCard,
    card_search,
    descend,
    emit_kb_retrieval,
    targeted_open,
)
from engine.kb.store import KBStore, parse_card, render_card, snapshot_id

__all__ = [
    "IngestReport",
    "KBStore",
    "Lanes",
    "as_lanes",
    "ProvenanceAccessDenied",
    "PurgeReport",
    "RestrictedStore",
    "SearchResult",
    "SourceDoc",
    "DeprecatedCard",
    "UseRestrictedCard",
    "apply_placeholders",
    "card_search",
    "descend",
    "emit_kb_retrieval",
    "ingest_document",
    "parse_card",
    "post_purge_sweep",
    "purge_client",
    "purge_org",
    "purge_pursuit_memory",
    "render_card",
    "scan",
    "scan_passed",
    "snapshot_id",
    "targeted_open",
]
