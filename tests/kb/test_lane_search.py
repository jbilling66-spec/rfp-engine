"""The memory-lane search (P17/C3, B75§3): one search, ONE idf over the
union of the joined catalogs; a firm-only search byte-identical to the
pre-P17 shape (the `lanes` field never on the line); lane provenance
riding the id prefix (pkb_/okb_) and the line; the replay law extended —
a lane line re-executes from its own fields plus the workspace mapping,
byte-identical. And the named B75§4a pin: the mapper eval's exact rates
are unmoved by the lane machinery landing.
"""

import pytest

from engine.kb import KBStore, Lanes, as_lanes, card_search, targeted_open
from engine.runlog import RunLogger, read_run

from tests.kb.fixtures.corpus import ingest_corpus
from tests.kb.fixtures.questions import QUESTIONS


def _memory_store(root, cards):
    store = KBStore(root)
    for card, body in cards:
        store.write_card(card, body, {"source_pursuit": "pur_lane_test"}, {})
    return store


PURSUIT_CARDS = [
    ({"kb_id": "pkb_priorprop01", "layer": "corpus",
      "title": "Prior proposal to this buyer — data migration approach",
      "summary": "How legacy data was converted and reconciled for this "
                 "same organization last cycle.",
      "type_tags": ["methodology"], "section_types": ["data_migration"]},
     "The prior engagement converted legacy ledgers in four waves with "
     "reconciliation checkpoints after each. Marker: LANEBODY-PRIOR."),
    ({"kb_id": "pkb_smenotes01", "layer": "corpus",
      "title": "SME technical notes for this pursuit",
      "summary": "Interface inventory and cutover constraints the SME "
                 "dictated for this response.",
      "type_tags": ["product_expertise"], "section_types": ["integration"]},
     "Eleven interfaces, two retired at cutover. Marker: LANEBODY-SME."),
    ({"kb_id": "pkb_restricted1", "layer": "corpus", "use_restriction": True,
      "title": "Restricted pursuit note",
      "summary": "A pursuit-lane card carrying use_restriction.",
      "section_types": ["data_migration"]},
     "Withheld content."),
]

ORG_CARDS = [
    ({"kb_id": "okb_obsweights1", "layer": "corpus",
      "title": "Org observation: evaluation weighting",
      "summary": "This organization weighted change management heavily "
                 "in prior evaluations.",
      "content_origin": "human_authored",
      "type_tags": ["ocm"], "section_types": ["change_management"]},
     "Firm-authored observation recorded by the pursuit lead."),
]


@pytest.fixture(scope="module")
def stores(tmp_path_factory):
    root = tmp_path_factory.mktemp("kb-lanes")
    firm, reports = ingest_corpus(root / "kb")
    assert all(r.status == "ingested" for r in reports)
    pursuit = _memory_store(root / "pur_demo" / "memory", PURSUIT_CARDS)
    org = _memory_store(root / "orgs" / "org_0001" / "memory", ORG_CARDS)
    return firm, pursuit, org


def _log(firm, run_id):
    return RunLogger(firm.root, run_id, "kb")


def _lines(firm, run_id):
    records = read_run(firm.root / "runs" / run_id / "run.jsonl")
    return [r for r in records if r["record_type"] == "kb_retrieval"]


def test_firm_only_bundle_is_byte_identical_to_a_bare_store(stores):
    """as_lanes(store) is the compat shape: same results, same scores,
    and the emitted kb payload identical — no lanes field, ever."""
    firm, _pursuit, _org = stores
    query = QUESTIONS[0][0]
    bare = card_search(firm, query, log=_log(firm, "run_0301"),
                       stage="drafting", agent="section_drafter")
    bundled = card_search(Lanes(firm=firm), query,
                          log=_log(firm, "run_0302"),
                          stage="drafting", agent="section_drafter")
    assert [(r.kb_id, r.score) for r in bare.results] == \
           [(r.kb_id, r.score) for r in bundled.results]
    bare_kb = _lines(firm, "run_0301")[-1]["kb"]
    bundled_kb = _lines(firm, "run_0302")[-1]["kb"]
    assert bare_kb == bundled_kb
    assert "lanes" not in bundled_kb and "org_id" not in bundled_kb


def test_union_search_is_one_idf_over_the_joined_catalogs(stores):
    """The pursuit card answers beside firm cards; catalog_size counts
    the UNION universe the one idf was computed over (B75§3b); the
    per-lane use_restriction is recorded, not dropped; and the search
    is deterministic — the same universe scores identically twice."""
    firm, pursuit, _org = stores
    lanes = Lanes(firm=firm, pursuit=pursuit)
    query = "how is legacy data converted and reconciled?"
    first = card_search(lanes, query, log=_log(firm, "run_0303"),
                        stage="drafting", agent="kb_mapper")
    again = card_search(lanes, query, log=_log(firm, "run_0304"),
                        stage="drafting", agent="kb_mapper")
    returned = [r.kb_id for r in first.results]
    assert "pkb_priorprop01" in returned, "the pursuit lane must answer"
    assert any(not r.kb_id.startswith("pkb_") for r in first.results), \
        "firm cards still answer beside the lane"
    assert [(r.kb_id, r.score) for r in first.results] == \
           [(r.kb_id, r.score) for r in again.results]
    assert {"kb_id": "pkb_restricted1", "reason": "use_restriction"} \
        in first.excluded
    line = _lines(firm, "run_0303")[-1]["kb"]
    assert line["lanes"] == ["firm", "pursuit"]
    assert "org_id" not in line
    firm_active = sum(1 for c in firm.list_cards()
                      if c.get("layer") != "fact_sheet"
                      and not c.get("use_restriction"))
    pursuit_active = sum(1 for c in pursuit.list_cards()
                         if not c.get("use_restriction"))
    assert line["catalog_size"] == firm_active + pursuit_active


def test_org_lane_requires_its_org_id(stores):
    firm, _pursuit, org = stores
    with pytest.raises(ValueError, match="org_id"):
        Lanes(firm=firm, org=org)


def test_org_lane_rides_the_line_and_lane_lines_replay(stores):
    """The replay law extended (B75§3a): a lane line re-executes from
    its own fields — lanes + org_id on the line, pursuit resolved via
    the workspace mapping — and returns byte-identical results."""
    firm, pursuit, org = stores
    lanes = Lanes(firm=firm, pursuit=pursuit, org=org, org_id="org_0001")
    card_search(lanes, "change management weighting for this organization",
                log=_log(firm, "run_0305"),
                stage="win_themes", agent="strategist")
    line = _lines(firm, "run_0305")[-1]["kb"]
    assert line["lanes"] == ["firm", "pursuit", "org"]
    assert line["org_id"] == "org_0001"
    assert "okb_obsweights1" in line["cards_returned"]

    # Replay: the line is sufficient. Rebuild the bundle from the line's
    # own fields (the workspace maps lane name -> store root, exactly as
    # the production resolver will) and re-execute.
    joined = line.get("lanes", [])
    rebuilt = Lanes(
        firm=firm,
        pursuit=pursuit if "pursuit" in joined else None,
        org=org if "org" in joined else None,
        org_id=line.get("org_id"),
    )
    again = card_search(rebuilt, line["query"],
                        log=_log(firm, "run_0306"),
                        stage="win_themes", agent="strategist",
                        facets=line.get("facets"))
    assert [r.kb_id for r in again.results] == line["cards_returned"]
    assert [e["kb_id"] for e in again.excluded] == line["excluded"]
    replay_line = _lines(firm, "run_0306")[-1]["kb"]
    assert replay_line == line


def test_prefix_dispatch_opens_the_minting_lane(stores):
    """targeted_open through a bundle reads the lane the id names — a
    pkb_ id opens the pursuit store's body, a firm id the firm's."""
    firm, pursuit, org = stores
    lanes = Lanes(firm=firm, pursuit=pursuit, org=org, org_id="org_0001")
    log = _log(firm, "run_0307")
    body = targeted_open(lanes, "pkb_smenotes01", log=log,
                         stage="drafting", agent="section_drafter",
                         query="plan:sec-01")
    assert "LANEBODY-SME" in body
    firm_id = next(c["kb_id"] for c in firm.list_cards()
                   if c.get("layer") != "fact_sheet"
                   and not c.get("use_restriction"))
    assert targeted_open(lanes, firm_id, log=log, stage="drafting",
                         agent="section_drafter", query="plan:sec-01")
    with pytest.raises(KeyError, match="no pursuit lane"):
        as_lanes(firm).store_for("pkb_smenotes01")


def test_mapper_suite_unmoved_by_lane_machinery():
    """The named B75§4a pin: the committed corpus is unenriched and the
    firm-only path is byte-stable, so the mapper eval's exact recorded
    rates hold — the intentional re-baseline belongs to the rehomed
    funded re-measure, not to this phase's machinery."""
    from engine.evals.mapper import evaluate_mapper_set
    report = evaluate_mapper_set()
    assert report["recall_at_5"] == 0.7368
    assert report["false_gap_rate"] == 0.0789
    assert report["true_gap_recall"] == 0.2917
