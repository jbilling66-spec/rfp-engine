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
    # (The fixture pursuit also carries an answered plan gap, which the
    # accept now proposes as a fact card — P26c — under its own door.)
    proposals = [p for p in ProposalStore(store.root).list(status="proposed")
                 if p["source"]["door"] == "flywheel"]
    assert [p["proposal_id"] for p in proposals] == flywheel["proposals"]
    assert len(flywheel["gap_proposals"]) == 1
    proposal = proposals[0]
    assert proposal["source"]["door"] == "flywheel"
    assert proposal["source"]["event_ids"] == [edit["event_id"]]
    assert proposal["kind"] == "update_card"
    assert proposal["kb_id"] == CARD, "P26c: the lesson names its card"
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
    assert len(ProposalStore(store.root).list()) == (
        len(first["proposals"]) + len(first["gap_proposals"]))
    assert second["gap_proposals"] == []
    raw = [json.loads(l) for l in (pursuit.root / "events" / "events.jsonl")
           .read_text(encoding="utf-8").splitlines()]
    assert sum(1 for e in raw if e["event_id"] == edit["event_id"]) == 2


def test_a_flywheel_failure_does_not_un_accept(accepting, monkeypatch):
    import engine.flywheel.routing as routing_mod

    client, pursuit, store, _ = accepting

    def boom(*_a, **_k):
        raise RuntimeError("routing table on fire")

    monkeypatch.setattr(routing_mod, "route_feedback", boom)
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


# --------------------------------------------- P26c: carried forward

def test_accepting_the_lesson_lands_it_on_the_card(accepting):
    """P1-43: the steward accepts the routed proposal through the web
    door and the lesson is ON the card — event id, pursuit, the
    reviewer's prose, the steward's name — visible from the KB row;
    the rest of the front matter and the body untouched."""
    client, pursuit, store, edit = accepting
    flywheel = client.post(f"/api/pursuits/{pursuit.pursuit_id}/accept",
                           json={}).json()["flywheel"]
    pid = flywheel["proposals"][0]
    before, body_before = store.read_card(CARD)
    r = client.post(f"/api/kb/proposals/{pid}/decide",
                    json={"decision": "accepted"})
    assert r.status_code == 200, r.text
    card, body = store.read_card(CARD)
    assert body == body_before
    assert card["lessons"] == [{
        "at": FIXED_AT, "by": "Jordan Reviewer", "proposal_id": pid,
        "pursuit_id": pursuit.pursuit_id, "event_ids": [edit["event_id"]],
        "before": BEFORE, "after": AFTER,
        "note": ProposalStore(store.root).read(pid)["note"]}]
    assert {k: v for k, v in card.items() if k != "lessons"} == before
    row = [c for c in client.get("/api/kb/cards").json()["cards"]
           if c["kb_id"] == CARD][0]
    assert len(row["lessons"]) == 1
    assert ProposalStore(store.root).read(pid)["status"] == "accepted"


def test_a_comment_and_a_waiver_reach_the_inbox_with_their_events(accepting):
    """P1-44: a finalized comment (with the agent's reply) and a waiver
    (its reason and claim on the annotated draft) become proposals at
    accept, each naming its source event; the second accept adds none."""
    client, pursuit, store, edit = accepting
    plan = json.loads((pursuit.root / "plan.json").read_text(encoding="utf-8"))
    section_id = plan["sections"][0]["section_id"]
    lane = EventsLane(pursuit)
    comment = lane.append(
        "comment", at="2026-08-07T09:05:00Z", actor="Pat",
        actor_role="pursuit_lead", section_id=section_id,
        comment_text="Lead with the outcome, not the method.",
        agent_reply="Reordered the opening to state the outcome first.")
    annotated = pursuit.read_artifact("drafts/annotated-draft.json")
    section = next(s for s in annotated["sections"] if s.get("claims"))
    claim = section["claims"][0]
    waived_at = "2026-08-07T09:06:00Z"
    claim.update({"status": "waived", "disposition": "waived",
                  "waived_by": "Cam", "waiver_reason":
                  "Verified offline against the signed engagement letter.",
                  "reasons": [f"waived over unsupported by Cam at {waived_at}"]})
    pursuit.write_artifact("annotated_draft", annotated,
                           name="drafts/annotated-draft.json")
    waive = lane.append("waive_block", at=waived_at, actor="Cam",
                        actor_role="contracts", claim_tier=claim["tier"],
                        section_id=section["section_id"])
    flywheel = client.post(f"/api/pursuits/{pursuit.pursuit_id}/accept",
                           json={}).json()["flywheel"]
    assert sorted(flywheel["routed"]) == sorted(
        [edit["event_id"], comment["event_id"], waive["event_id"]])
    proposals = {p["source"]["event_ids"][0]: p
                 for p in ProposalStore(store.root).list(status="proposed")
                 if p["source"].get("event_ids")}
    note = proposals[comment["event_id"]]
    assert note["kind"] == "playbook_note" and note["target"] == "playbook"
    assert note["diff"]["agent_reply"]["after"].startswith("Reordered")
    tuning = proposals[waive["event_id"]]
    assert tuning["kind"] == "validation_tuning_note"
    assert tuning["diff"]["claim"]["after"] == claim["text"]
    assert tuning["diff"]["waiver_reason"]["after"].startswith("Verified offline")
    assert tuning["source"]["section_id"] == section["section_id"]
    again = client.post(f"/api/pursuits/{pursuit.pursuit_id}/accept",
                        json={}).json()["flywheel"]
    assert again["routed"] == [] and again["proposals"] == []


def test_an_answered_gap_reaches_the_inbox_once(accepting):
    """B116 §5 (the owner's call): every answered gap with no proposal
    yet becomes a fact-card proposal at accept; one the answerer already
    proposed through the opt-in door is not proposed twice; a second
    accept adds none. Nothing enters the corpus — the store is unchanged
    until a steward accepts with owner and verified date."""
    from engine.kb.curation import propose_gap_answer_card

    client, pursuit, store, _ = accepting
    plan_path = pursuit.root / "plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    pid = pursuit.pursuit_id
    plan["sections"][0]["gaps"] = [
        {"gap_id": f"gap_{pid}_plan_01", "kind": "needs_sme",
         "question_to_human": "How many validated waves does the cutover use?",
         "status": "answered", "answer": "Four validated waves."},
        {"gap_id": f"gap_{pid}_plan_02", "kind": "needs_sme",
         "question_to_human": "Which platform version is certified?",
         "status": "answered", "answer": "Release 24.2."},
        {"gap_id": f"gap_{pid}_plan_03", "kind": "needs_sme",
         "question_to_human": "Unanswered.", "status": "open"}]
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    opted = propose_gap_answer_card(
        store.root, gap=plan["sections"][0]["gaps"][0], pursuit_id=pid,
        operator="Astrid", at="2026-08-07T09:00:00Z")
    cards_before = [c["kb_id"] for c in store.list_cards()]
    flywheel = client.post(f"/api/pursuits/{pid}/accept",
                           json={}).json()["flywheel"]
    assert len(flywheel["gap_proposals"]) == 1
    new = ProposalStore(store.root).read(flywheel["gap_proposals"][0])
    assert new["source"] == {"door": "gap_answer", "pursuit_id": pid,
                             "gap_id": f"gap_{pid}_plan_02",
                             "operator": "Jordan Reviewer"}
    assert new["kind"] == "new_card" and new["target"] == "fact_sheet"
    assert "Release 24.2." in new["diff"]["body"]["after"]
    gap_ids = sorted(p["source"]["gap_id"] for p in ProposalStore(store.root).list()
                     if p["source"].get("gap_id"))
    assert gap_ids == [f"gap_{pid}_plan_01", f"gap_{pid}_plan_02"]
    assert ProposalStore(store.root).read(opted)["source"]["operator"] == "Astrid"
    assert [c["kb_id"] for c in store.list_cards()] == cards_before, \
        "the inbox, never the corpus"
    again = client.post(f"/api/pursuits/{pid}/accept", json={}).json()["flywheel"]
    assert again["gap_proposals"] == []


def test_the_buyer_name_is_placeholdered_in_the_proposal(accepting):
    """Pursuit prose names the buyer; what reaches the inbox — and from
    there a firm card or the drafter's prompt — carries [CLIENT]."""
    client, pursuit, store, _ = accepting
    buyer = pursuit.read_frozen("bid_brief")["buyer"]["name"]
    assert buyer, "the fixture brief names its buyer"
    plan = json.loads((pursuit.root / "plan.json").read_text(encoding="utf-8"))
    section_id = plan["sections"][0]["section_id"]
    EventsLane(pursuit).append(
        "edit", at="2026-08-07T09:07:00Z", actor="Pat",
        actor_role="pursuit_lead", section_id=section_id,
        before=f"{buyer} runs 40 sites.", after=f"{buyer} runs 14 sites.",
        edit_reason="factual")
    client.post(f"/api/pursuits/{pursuit.pursuit_id}/accept", json={})
    texts = [v for p in ProposalStore(store.root).list()
             for change in p["diff"].values()
             for v in change.values() if isinstance(v, str)]
    assert any("[CLIENT] runs 14 sites." == v for v in texts)
    assert not any(buyer in v for v in texts)
