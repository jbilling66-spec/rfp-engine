"""KB command group: seed | ingest | search | open | snapshot | purge |
where-used | provenance.

`seed` builds the committed synthetic store from the fixture corpus via the
scripted FakeCaller — a dev command that needs the repo checkout (the
fixtures live under tests/). `ingest` is the production door: `--live`
(P28, P1-45) runs both readers through the traced live caller — refused by
construction without RFP_LIVE=1, a key and a priced table, under a
per-document spend budget; offline it takes two wire-response files
standing in for the two readers.
"""

import json
from engine.workspace.pursuit import mint_run_id
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_KB = _REPO_ROOT / "kb"


def _store(args):
    from engine.kb import KBStore
    return KBStore(Path(args.kb))


def _new_log(store):
    from engine.runlog import RunLogger
    return RunLogger(store.root, mint_run_id(store.root / "runs"), "kb")


def _cmd_kb_seed(args) -> int:
    try:
        from tests.kb.fixtures.corpus import ingest_corpus
    except ImportError:
        print("seed needs the repo checkout (fixture corpus under tests/)",
              file=sys.stderr)
        return 1
    store, reports = ingest_corpus(Path(args.kb))
    for r in reports:
        merged = f" ({len(r.merged)} merged)" if r.merged else ""
        print(f"{r.doc_id}: {r.status}, +{len(r.cards_written)} cards{merged}")
    print(f"cards: {len(store.list_cards())}  snapshot: {store.snapshot()}")
    return 0 if all(r.status == "ingested" for r in reports) else 1


def _live_ingest_caller(budget_usd: float):
    """P1-45 (P28): the production door's live caller — LiveCaller refuses
    construction without RFP_LIVE=1, a key and a priced table (B30(e));
    nothing is constructed or minted before that check. The budget bounds
    ONE document's two reads — a runaway guard, not a price."""
    from engine.llm import (LiveCaller, SpendBudget, TracedCaller,
                            load_env_file, model_prices)

    load_env_file(_REPO_ROOT / ".env")  # the one sanctioned .env read (B34(22))
    live_caller = LiveCaller()  # refusals are named, and spend nothing
    prices = model_prices()["prices"]
    budget = SpendBudget(total_usd=budget_usd, max_calls=8)

    def make_caller(log):
        return TracedCaller(live_caller, log, prices=prices, budget=budget)

    return make_caller


def _scripted_ingest_caller(args):
    """Offline: two readers, two replies — both are the operator's."""
    from engine.llm import FakeCaller, TracedCaller

    if not args.wire:
        print("REFUSED: offline ingestion needs --wire and --reviewer-wire "
              "(scripted replies for the two readers), or --live",
              file=sys.stderr)
        return None
    if not args.reviewer_wire:
        print("REFUSED: --reviewer-wire is required alongside --wire — the "
              "anonymization reviewer (the second reader) needs its own "
              "scripted reply offline", file=sys.stderr)
        return None
    wire_text = Path(args.wire).read_text(encoding="utf-8")
    review_text = Path(args.reviewer_wire).read_text(encoding="utf-8")

    def make_caller(log):
        return TracedCaller(FakeCaller({"ingestion_agent": wire_text,
                                        "anonymization_reviewer": review_text}),
                            log)

    return make_caller


def neutral_doc_handle(path: Path) -> str:
    """P29a (P1-47): the logical-document key the CLI door mints — a
    digest of the case-folded stem, never the stem. Same filename, same
    handle, so `prior_models` still finds a re-ingest's lineage."""
    import hashlib

    digest = hashlib.sha256(path.stem.casefold().encode("utf-8")).hexdigest()
    return f"doc_{digest[:12]}"


def _cmd_kb_ingest(args) -> int:
    from engine.kb import SourceDoc, ingest_document
    from engine.kb.read import read_source

    if args.live:
        if args.reviewer_wire:
            print("REFUSED: --reviewer-wire is an offline flag; --live runs "
                  "both readers through the live caller", file=sys.stderr)
            return 1
        try:
            make_caller = _live_ingest_caller(args.budget_usd)
        except Exception as exc:  # noqa: BLE001 — the refusal is the message
            print(f"ingest --live refused: {exc}", file=sys.stderr)
            return 1
    else:
        make_caller = _scripted_ingest_caller(args)
        if make_caller is None:
            return 1
    store = _store(args)
    log = _new_log(store)
    caller = make_caller(log)
    source = read_source(Path(args.file))  # python-docx primary here (B57)
    doc = SourceDoc(
        # P29a (P1-47): a filename is, in practice, the client's name. The
        # firm store never records it — the handle is a digest of the stem
        # (stable across re-ingests of the same document, so lineage
        # holds) and the original name rides the RESTRICTED meta only.
        doc_id=neutral_doc_handle(Path(args.file)),
        source_name=Path(args.file).name,
        text=source.text,
        source_client=args.client, source_pursuit=args.pursuit,
        outcome=args.outcome, date=args.date, authored_by=args.authored_by,
        extractor=source.extractor,
        extraction_fingerprint=source.fingerprint,
        media=source.media,
        elements=source.elements,
        source_bytes=Path(args.file).read_bytes(),
    )
    report = ingest_document(store, caller, log, doc)
    print(f"{report.doc_id}: {report.status}, +{len(report.cards_written)} cards")
    if report.status == "blocked":
        print(f"anonymization findings route to: {report.route_to}",
              file=sys.stderr)
        for finding in report.findings:
            print(f"  {finding.location}: {finding.matched!r}", file=sys.stderr)
    return 0 if report.status == "ingested" else 1


def _cmd_kb_search(args) -> int:
    from engine.kb import card_search
    store = _store(args)
    result = card_search(store, args.query, k=args.k, log=_new_log(store),
                         stage="drafting", agent="cli")
    for r in result.results:
        flags = " [canonical]" if r.card.get("canonical_block") else ""
        print(f"{r.kb_id}  {r.score:8.4f}  {r.card.get('title', '')}{flags}")
    for e in result.excluded:
        print(f"excluded: {e['kb_id']} ({e['reason']})")
    if not result.results:
        print("(empty result — a legitimate gap, not an error)")
    return 0


def _cmd_kb_open(args) -> int:
    from engine.kb import UseRestrictedCard, targeted_open
    store = _store(args)
    try:
        body = targeted_open(store, args.kb_id, log=_new_log(store),
                             stage="drafting", agent="cli", query=args.kb_id)
    except UseRestrictedCard as e:
        print(f"refused: {e}", file=sys.stderr)
        return 1
    print(body)
    return 0


def _cmd_kb_snapshot(args) -> int:
    from engine.kb import snapshot_id
    print(snapshot_id(Path(args.kb)))
    return 0


def _cmd_kb_purge(args) -> int:
    from engine.kb import purge_client
    from engine.workspace.lock import WorkspaceLocked, workspace_lock
    # The purge cascades into every pursuit under --pursuits — that root
    # IS a served workspace, so it takes the server's lock (P25 item 2,
    # P0-4) and refuses beside a live server rather than racing it.
    try:
        lock = workspace_lock(Path(args.pursuits), holder="engine kb purge")
    except WorkspaceLocked as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    with lock:
        report = purge_client(_store(args), args.client, actor=args.actor,
                              pursuits_root=Path(args.pursuits))
    acct = report.accounting or {}
    print(f"purged: {len(report.purged)} cards; held (legal_hold): "
          f"{report.held or 'none'}")
    print(f"cascade: L0 {len(acct.get('l0_sources', []))} sources, "
          f"L1 {len(acct.get('l1_models', []))} models, "
          f"drafts {len(acct.get('drafts', []))} artifacts "
          f"(accounting: {report.accounting_path})")
    print(f"post-purge sweep: {'CLEAN' if report.swept_clean else 'FINDINGS'}")
    for finding in report.sweep_findings:
        print(f"  {finding}", file=sys.stderr)
    return 0 if report.swept_clean else 1


def _cmd_kb_stats(args) -> int:
    from engine.kb.curation import chunk_size_distribution
    dist = chunk_size_distribution(_store(args))
    if not dist["n"]:
        print("no chunk-bearing cards")
        return 0
    print(f"chunks: {dist['n']}  chars min {dist['min']}  "
          f"p50 {dist['p50']}  p95 {dist['p95']}  max {dist['max']}  "
          f"total {dist['total_chars']}")
    print("size is recorded, never enforced (R5) — an outlier is an "
          "extraction finding, not content to split")
    return 0


def _cmd_kb_where_used(args) -> int:
    from engine.kb import ProvenanceAccessDenied
    store = _store(args)
    try:
        hits = store.restricted.reverse_index(args.name, actor=args.actor)
    except ProvenanceAccessDenied as e:
        print(f"denied: {e}", file=sys.stderr)
        return 1
    for hit in hits:
        print(f"{hit['kb_id']}  ({hit['placeholder']})")
    if not hits:
        print("no usage found")
    return 0


def _cmd_kb_provenance(args) -> int:
    from engine.kb import ProvenanceAccessDenied
    store = _store(args)
    try:
        record = store.restricted.read(args.kb_id, actor=args.actor,
                                       purpose=args.purpose)
    except ProvenanceAccessDenied as e:
        print(f"denied: {e}", file=sys.stderr)
        return 1
    print(json.dumps(record, indent=2, sort_keys=True))
    return 0


def register(sub) -> None:
    kb = sub.add_parser("kb", help="knowledge base: seed, search, purge, audit")
    kbsub = kb.add_subparsers(dest="kb_command", required=True)

    def _p(name, fn, help_text):
        parser = kbsub.add_parser(name, help=help_text)
        parser.add_argument("--kb", default=str(_DEFAULT_KB))
        parser.set_defaults(fn=fn)
        return parser

    _p("seed", _cmd_kb_seed, "build the committed store from the fixture corpus")

    ingest = _p("ingest", _cmd_kb_ingest, "ingest one firm-authored document")
    ingest.add_argument("--file", required=True)
    reader = ingest.add_mutually_exclusive_group()
    reader.add_argument("--wire", default=None,
                        help="scripted wire-JSON reply for the ingestion agent "
                             "(offline; pair with --reviewer-wire)")
    reader.add_argument("--live", action="store_true",
                        help="P1-45: run both readers through the live caller "
                             "(requires RFP_LIVE=1; refuses otherwise)")
    ingest.add_argument("--reviewer-wire", default=None,
                        help="scripted wire-JSON reply for the anonymization "
                             "reviewer (P28: the second reader; offline only)")
    ingest.add_argument("--budget-usd", type=float, default=5.0,
                        help="--live: the spend ceiling for this one document "
                             "(a runaway guard; two fast-tier reads cost cents)")
    ingest.add_argument("--client", required=True)
    ingest.add_argument("--pursuit", required=True)
    ingest.add_argument("--outcome", default="unknown")
    ingest.add_argument("--date", required=True)
    ingest.add_argument("--authored-by", default="firm")

    search = _p("search", _cmd_kb_search, "card search with full retrieval trace")
    search.add_argument("query")
    search.add_argument("--k", type=int, default=8)

    open_ = _p("open", _cmd_kb_open, "targeted open of one card body")
    open_.add_argument("kb_id")

    _p("snapshot", _cmd_kb_snapshot, "print the KB content snapshot id")

    purge = _p("purge", _cmd_kb_purge, "purge a source client + sweep (D1)")
    purge.add_argument("--client", required=True)
    purge.add_argument("--actor", required=True)
    purge.add_argument("--pursuits", default=str(_REPO_ROOT / "pursuits"),
                       help="pursuit workspaces root — derived draft "
                            "content citing purged cards cascades (R8)")

    _p("stats", _cmd_kb_stats,
       "chunk-size distribution (R5: recorded, never enforced)")

    where = _p("where-used", _cmd_kb_where_used,
               "right of review: where is this name used?")
    where.add_argument("name")
    where.add_argument("--actor", required=True)

    prov = _p("provenance", _cmd_kb_provenance,
              "authorized read of one card's restricted provenance")
    prov.add_argument("kb_id")
    prov.add_argument("--actor", required=True)
    prov.add_argument("--purpose", default="audit")
