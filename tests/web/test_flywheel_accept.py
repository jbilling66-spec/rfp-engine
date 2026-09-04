"""P1-41 (P26b-2): the flywheel's one call site. Accepting a pursuit
routes its reviewer edits into steward proposals (nothing self-merges),
appends each routed event's revised line under the same id (D30), and
writes edit_survival onto every cited card from the whole corpus through
the resolver's own production filter — so the number on the card is the
number the metric reports. A second accept learns nothing new. A learner
failure is reported in the response and never undoes the accept."""

import json

import pytest
from fastapi.testclient import TestClient

from engine.flywheel.proposals import ProposalStore
from engine.flywheel.survival import card_survival
from engine.kb.store import KBStore
from engine.metrics.resolver import Corpus, resolve
from engine.web.events import EventsLane
from engine.web.server import create_app
from tests.validation.fixtures.validations import run_validation_package
from tests.web.conftest import FIXED_AT, raising_caller, sign_in

PROV = {"source_pursuit": "pur_x", "source_client": "Fixture County",
        "date": "2026-01-01", "ingested_by": "ingestion_agent"}
CARD = "kb_cited0001"
BEFORE = ("Our migration factory ran seven mock conversions before the "
          "first production load.")
AFTER = ("Our migration factory ran nine mock conversions before the "
         "first production load.")


def _plant_production_cite(pursuit, section_id):
    """The fixture chain's runs are dry_run, which the production filter
    drops — so the cite the flywheel attributes to lives in a run of its
    own, headed mode=live."""
    run_dir = pursuit.root / "runs" / "run_0090"
    run_dir.mkdir(parents=True)
    pid = pursuit.pursuit_id
    records = [
        {"run_id": "run_0090", "pursuit_id": pid, "seq": 0, "ts": FIXED_AT,
         "record_type": "run_start", "run": {"mode": "live"}},
        {"run_id": "run_0090", "pursuit_id": pid, "seq": 1, "ts": FIXED_AT,
         "record_type": "kb_retrieval", "stage": "drafting",
         "agent": "section_drafter",
         "kb": {"query": "q", "step": "cite", "cards_returned": [CARD],
                "cards_opened": [CARD], "cards_cited": [CARD],
                "excluded": [], "empty_result": False},
         "target": {"section_id": section_id}},
    ]
    (run_dir / "run.jsonl").write_text(
        "\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")


@pytest.fixture
def accepting(tmp_path):
    workspace = tmp_path
    pursuit, report, _ = run_validation_package(workspace)
    assert report.status == "complete"
    store = KBStore(workspace / "kb")  # BEFORE create_app: the app's KB
    store.write_card(
        {"kb_id": CARD, "layer": "corpus", "doc_kind": "section_exemplar",
         "title": "Data Migration Approach", "summary": "Migration factory.",
         "owner": "Delivery Lead"}, "Body.", PROV, {})
    plan = json.loads((pursuit.root / "plan.json").read_text(encoding="utf-8"))
    section_id = plan["sections"][0]["section_id"]
    _plant_production_cite(pursuit, section_id)
    lane = EventsLane(pursuit)
    edit = lane.append("edit", at="2026-08-07T09:00:00Z", actor="Pat",
                       actor_role="pursuit_lead", section_id=section_id,
                       before=BEFORE, after=AFTER, edit_reason="factual")
    app = create_app(workspace, make_caller=raising_caller,
                     now=lambda: FIXED_AT)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        sign_in(client)
        yield client, pursuit, store, edit


def test_accept_routes_edits_and_writes_card_signals(accepting):
    client, pursuit, store, edit = accepting
    r = client.post(f"/api/pursuits/{pursuit.pursuit_id}/accept", json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "accept"
    flywheel = body["flywheel"]
    assert flywheel["routed"] == [edit["event_id"]]
    assert flywheel["signals_written"] == [CARD]
    assert len(flywheel["proposals"]) == 1

    # 1. A proposal the steward decides — machine-drafted, never merged.
    proposals = ProposalStore(store.root).list(status="proposed")
    assert [p["proposal_id"] for p in proposals] == flywheel["proposals"]
    proposal = proposals[0]
    assert proposal["source"]["door"] == "flywheel"
    assert proposal["source"]["event_ids"] == [edit["event_id"]]
    assert proposal["kind"] == "update_card"
    assert proposal["diff"]["text"] == {"before": BEFORE, "after": AFTER}
    assert "operator" not in proposal["source"], "a machine proposal"

    # 2. The revised line: same id, stamped with the server's clock.
    raw = [json.loads(l) for l in (pursuit.root / "events" / "events.jsonl")
           .read_text(encoding="utf-8").splitlines()]
    revised = [e for e in raw if e["event_id"] == edit["event_id"]]
    assert len(revised) == 2, "the original stays; a revised copy follows"
    assert revised[1]["flywheel_routing"]["processed_at"] == body["at"]
    assert revised[1]["flywheel_routing"]["action_taken"] == (
        f"proposal:{proposal['proposal_id']}")
    seen = [e for e in EventsLane(pursuit).read()
            if e["event_id"] == edit["event_id"]]
    assert len(seen) == 1 and "flywheel_routing" in seen[0], "last wins"

    # 3. The card carries the signal the resolver reports (B40/D18).
    card, _ = store.read_card(CARD)
    corpus = Corpus(pursuit.root.parent)
    expected = card_survival(corpus.runs(), corpus.events())[CARD]["survival"]
    assert card["edit_survival"] == expected
    assert 0.9 < expected < 1.0, "one word changed in a light edit"
    survival = resolve("edit_survival_rate", corpus)
    assert survival["value"] == expected
    lag = resolve("lesson_to_draft_lag_days", corpus)
    assert lag["n"] == 1 and lag["value"] == 2.0  # 08-07 -> 08-09


def test_a_second_accept_learns_nothing_new(accepting):
    client, pursuit, store, edit = accepting
    url = f"/api/pursuits/{pursuit.pursuit_id}/accept"
    first = client.post(url, json={}).json()["flywheel"]
    card_after_first = (store.root / "cards" / f"{CARD}.md").read_bytes()
    second = client.post(url, json={}).json()["flywheel"]
    assert second["routed"] == [] and second["proposals"] == []
    assert second["signals_written"] == [CARD], "recomputed, converged"
    assert (store.root / "cards" / f"{CARD}.md").read_bytes() == card_after_first
    assert len(ProposalStore(store.root).list()) == len(first["proposals"])
    raw = [json.loads(l) for l in (pursuit.root / "events" / "events.jsonl")
           .read_text(encoding="utf-8").splitlines()]
    assert sum(1 for e in raw if e["event_id"] == edit["event_id"]) == 2


def test_a_flywheel_failure_does_not_un_accept(accepting, monkeypatch):
    import engine.flywheel.routing as routing_mod

    client, pursuit, store, _ = accepting

    def boom(*_a, **_k):
        raise RuntimeError("routing table on fire")

    monkeypatch.setattr(routing_mod, "route_edits", boom)
    r = client.post(f"/api/pursuits/{pursuit.pursuit_id}/accept", json={})
    assert r.status_code == 200
    assert r.json()["flywheel"] == {
        "error": "RuntimeError: routing table on fire"}
    events = EventsLane(pursuit).read()
    assert events[-1]["kind"] == "accept", "the accept is durable"
    plan = json.loads((pursuit.root / "plan.json").read_text(encoding="utf-8"))
    stamped = [s for s in plan["sections"] if "draft_status" in s]
    assert stamped and all(s["draft_status"] == "final" for s in stamped)
    assert "edit_survival" not in store.read_card(CARD)[0]


def test_a_kb_outside_the_workspace_learns_nothing(tmp_path):
    """The server falls back to the repository's seed store when a
    workspace has no kb/; learned signals never land on a shared store
    — the learner reports the skip instead."""
    from engine.web.learn import learn_from_accept

    elsewhere = tmp_path / "shared" / "kb"
    workspace = tmp_path / "ws"
    workspace.mkdir()
    result = learn_from_accept(workspace, elsewhere, "pur_any", at=FIXED_AT)
    assert "outside the workspace" in result["skipped"]
    assert not elsewhere.exists(), "nothing was created there either"
