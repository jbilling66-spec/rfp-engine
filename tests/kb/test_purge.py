"""Purge acceptance (D1): a purged client leaves no retrievable trace, the
closure follows merges and derivation links, legal hold overrides purge and
is reported (D2), and the sweep verdict lands in the access log.
"""

import json

from engine.kb import KBStore, card_search, purge_client
from engine.runlog import RunLogger

from tests.kb.fixtures.corpus import PLANTED, ingest_corpus

PROV_X = {"source_pursuit": "pur_x", "source_client": "Client X",
          "date": "2025-01-01", "ingested_by": "ingestion_agent"}
PROV_Y = {"source_pursuit": "pur_y", "source_client": "Client Y",
          "date": "2025-02-01", "ingested_by": "ingestion_agent"}


def _retrievable_text(store) -> str:
    return " ".join(
        " ".join(p.read_text(encoding="utf-8").lower().split())
        for p in (store.root / "cards").glob("*.md")
    )


def _access_lines(store) -> list[dict]:
    return [
        json.loads(line)
        for line in store.restricted.access_log.read_text().splitlines()
    ]


def test_purge_client_leaves_no_retrievable_trace(tmp_path):
    store, _ = ingest_corpus(tmp_path / "kb")
    before = len(store.list_cards())
    report = purge_client(store, "Meridian Health Partners", actor="owner")
    assert report.swept_clean is True
    assert report.held == []
    assert len(report.purged) >= 4
    assert len(store.list_cards()) == before - len(report.purged)

    text = _retrievable_text(store)
    for identifier in PLANTED["resp_01"] + PLANTED["resp_02"] + PLANTED["resp_03"]:
        assert identifier.lower() not in text
    assert "rollback rehearsal" not in text  # a purged card's body is gone

    log = RunLogger(store.root, "run_9000", "kb")
    result = card_search(store, "two-wave ERP cutover payroll parallel gates",
                         log=log, stage="drafting", agent="section_drafter")
    assert not (set(report.purged) & {r.kb_id for r in result.results})

    actions = [(l["action"], l["granted"]) for l in _access_lines(store)]
    assert ("delete", True) in actions
    assert ("sweep", True) in actions


def test_purge_removes_cross_client_merged_card(tmp_path):
    store, _ = ingest_corpus(tmp_path / "kb")
    training = [
        c for c in store.list_cards()
        if "super-user" in store.read_card(c["kb_id"])[1]
    ]
    assert len(training) == 1  # the merged Cascade+Harborlight card
    report = purge_client(store, "Cascade Valley Medical Center", actor="owner")
    assert report.swept_clean is True
    assert training[0]["kb_id"] in report.purged
    assert not store.card_exists(training[0]["kb_id"])


def test_purge_follows_derived_from_links(tmp_path):
    store = KBStore(tmp_path / "kb")
    store.write_card(
        {"kb_id": "kb_parent0001", "layer": "corpus",
         "summary": "Original section from [CLIENT]."},
        "Original body.", PROV_X, {"Client X": "CLIENT"})
    store.write_card(
        {"kb_id": "kb_derived001", "layer": "playbook", "doc_kind": "lesson",
         "summary": "Lesson distilled from a [CLIENT] section."},
        "Derived lesson body.",
        {**PROV_Y, "derived_from": ["kb_parent0001"]}, {})
    report = purge_client(store, "Client X", actor="owner")
    assert sorted(report.purged) == ["kb_derived001", "kb_parent0001"]
    assert store.list_cards() == []
    assert report.swept_clean is True


def test_legal_hold_blocks_purge_and_is_reported(tmp_path):
    store = KBStore(tmp_path / "kb")
    store.write_card(
        {"kb_id": "kb_held000001", "layer": "corpus", "legal_hold": True,
         "summary": "Held card from [CLIENT]."},
        "Held body.", PROV_X, {"Client X": "CLIENT"})
    store.write_card(
        {"kb_id": "kb_free000001", "layer": "corpus",
         "summary": "Purgeable card from [CLIENT]."},
        "Free body.", PROV_X, {"Client X": "CLIENT"})
    report = purge_client(store, "Client X", actor="owner")
    assert report.purged == ["kb_free000001"]
    assert report.held == ["kb_held000001"]
    assert store.card_exists("kb_held000001")
    assert report.swept_clean is True  # held survivor is reported, not a leak


def test_purge_unknown_client_is_clean_noop(tmp_path):
    store, _ = ingest_corpus(tmp_path / "kb")
    before = store.snapshot()
    report = purge_client(store, "Northwind Regional Health", actor="owner")
    assert report.purged == [] and report.held == []
    assert report.swept_clean is True
    assert store.snapshot() == before


# ---------------------------------------- C16: the L0–L3 cascade (WP13 R8)

def test_cascade_removes_l1_models_and_l0_sources_with_full_accounting(tmp_path):
    store, _ = ingest_corpus(tmp_path / "kb")
    meridian_cds = {
        c.get("canonical_doc_id") for c in store.list_cards()
        if any(s.get("source_client") == "Meridian Health Partners"
               for s in json.loads(
                   (store.root / "restricted" / "provenance"
                    / f"{c['kb_id']}.json").read_text())["sources"])
        if c.get("canonical_doc_id")
    }
    assert meridian_cds, "the fixture must give Meridian canonical models"
    report = purge_client(store, "Meridian Health Partners", actor="owner")
    assert report.swept_clean is True

    acct = report.accounting
    # Every stage present, every closure member accounted exactly once.
    assert set(acct["l3_cards"]) == set(report.purged)
    assert acct["held_cards"] == []
    for cd in acct["l1_models"]:
        assert not (store.root / "canonical" / f"{cd}.json").exists()
    for cd in acct["l0_sources"]:
        assert not store.restricted.source_exists(
            cd, actor="owner", purpose="audit")
    assert set(acct["l1_models"]) >= meridian_cds
    assert "no persisted state" in acct["l4_statement"]  # KB8 disposition
    # Other clients' layers survive.
    assert store.restricted.list_source_ids(actor="owner", purpose="audit")
    assert list((store.root / "canonical").glob("*.json"))
    # The accounting is persisted in the restricted store and the access
    # log points at it.
    assert (store.root / "restricted" / "purges").is_dir()
    assert report.accounting_path.endswith(".json")
    sweep_lines = [l for l in _access_lines(store) if l["action"] == "sweep"]
    assert sweep_lines[-1]["name"] in report.accounting_path


def test_held_card_holds_its_parent_model_and_source(tmp_path):
    store, _ = ingest_corpus(tmp_path / "kb")
    held = next(c for c in store.list_cards()
                if c.get("canonical_doc_id")
                and any(s.get("source_client") == "Meridian Health Partners"
                        for s in json.loads(
                            (store.root / "restricted" / "provenance"
                             / f"{c['kb_id']}.json").read_text())["sources"]))
    store.update_card_front(held["kb_id"], legal_hold=True)
    report = purge_client(store, "Meridian Health Partners", actor="owner")
    cd = held["canonical_doc_id"]
    assert held["kb_id"] in report.held
    assert (store.root / "canonical" / f"{cd}.json").exists(), \
        "you cannot delete the parent of retained evidence"
    assert store.restricted.source_exists(cd, actor="owner", purpose="audit")
    assert cd in report.accounting["held_models"]
    assert cd in report.accounting["held_sources"]


def test_blocked_ingest_l0_is_reachable_by_its_clients_purge(tmp_path):
    """The gap C16 closed: a blocked ingest retains L0 but mints no
    cards and no provenance record — the restricted meta's
    source_client is the only purge linkage it has."""
    from engine.kb import SourceDoc, ingest_document
    from engine.llm import FakeCaller, TracedCaller

    store = KBStore(tmp_path / "kb")
    log = RunLogger(store.root, "run_0001", "kb")
    wire = json.dumps({"chunk_annotations": [], "qa_pairs": [],
                       "identifiers": [],
                       "client_descriptor": "an org"})
    caller = TracedCaller(FakeCaller({"ingestion_agent": wire}), log)
    doc = SourceDoc(doc_id="leaky", text="# DOC:leaky\n\n## S\n\n"
                    "Zephyrline's team praised the cutover.\n",
                    source_client="Zephyrline Logistics",
                    source_pursuit="pur_z",
                    outcome="won", date="2026-08-01", authored_by="firm",
                    known_identifiers={"Zephyrline Logistics": "CLIENT"})
    report = ingest_document(store, caller, log, doc)
    assert report.status == "blocked"
    assert store.restricted.list_source_ids(actor="owner", purpose="audit"), \
        "L0 retained on block"
    purge = purge_client(store, "Zephyrline Logistics", actor="owner")
    assert store.restricted.list_source_ids(
        actor="owner", purpose="audit") == []
    assert len(purge.accounting["l0_sources"]) == 1


def test_draft_citing_a_purged_card_cascades_and_is_accounted(tmp_path):
    store, _ = ingest_corpus(tmp_path / "kb")
    victim = next(
        c["kb_id"] for c in store.list_cards()
        if any(s.get("source_client") == "Meridian Health Partners"
               for s in json.loads(
                   (store.root / "restricted" / "provenance"
                    / f"{c['kb_id']}.json").read_text())["sources"]))
    pursuits = tmp_path / "pursuits"
    drafts = pursuits / "pur_demo" / "drafts"
    drafts.mkdir(parents=True)
    (drafts / "draft.json").write_text(json.dumps({
        "sections": [
            {"section_id": "s1", "cards_cited": [victim]},
            {"section_id": "s2", "cards_cited": []},
        ]}), encoding="utf-8")
    clean = pursuits / "pur_clean" / "drafts"
    clean.mkdir(parents=True)
    (clean / "draft.json").write_text(json.dumps({
        "sections": [{"section_id": "s1", "cards_cited": []}]}),
        encoding="utf-8")

    report = purge_client(store, "Meridian Health Partners", actor="owner",
                          pursuits_root=pursuits)
    assert not (drafts / "draft.json").exists()
    assert (clean / "draft.json").exists()
    assert report.accounting["drafts"] == [{
        "pursuit": "pur_demo", "artifact": "drafts/draft.json",
        "sections": ["s1"]}]
