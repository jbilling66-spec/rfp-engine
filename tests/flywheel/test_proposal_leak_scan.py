"""P1-46 (P28): flywheel proposals pass the same scanner a firm document
passes at ingestion. A proposal whose strings still carry an identifier
residue after cleaning is not written; the event is revised `blocked`
with locations only, and the learn doors report it.
"""

from engine.flywheel.proposals import ProposalStore
from engine.flywheel.routing import BLOCKED_PREFIX, route_feedback
from engine.kb.store import KBStore
from engine.web.learn import _cleaners

AT = "2026-09-05T00:00:00Z"
BUYER = {"Northwind Regional Health": "CLIENT"}


def _edit(before, after, **over):
    event = {"event_id": "ev_1", "pursuit_id": "pur_a", "kind": "edit",
             "at": "2026-09-04T12:00:00Z", "actor_role": "pursuit_lead",
             "section_id": "s1", "before": before, "after": after}
    event.update(over)
    return event


def _comment(text, reply, **over):
    event = {"event_id": "ev_c1", "pursuit_id": "pur_a", "kind": "comment",
             "at": "2026-09-04T12:00:00Z", "actor_role": "pursuit_lead",
             "section_id": "s1", "comment_text": text, "agent_reply": reply}
    event.update(over)
    return event


def _store(tmp_path):
    return KBStore(tmp_path / "kb")


def test_an_edit_carrying_the_buyers_acronym_is_blocked_not_written(tmp_path):
    store = _store(tmp_path)
    clean, verify = _cleaners(BUYER)
    revised = route_feedback(
        [_edit("NRH runs 40 sites.", "NRH runs 14 sites.")],
        store, at=AT, anonymize=clean, verify=verify)
    action = revised[0]["flywheel_routing"]["action_taken"]
    assert action == BLOCKED_PREFIX + "text.after,text.before"
    assert "NRH" not in action  # locations only, never the text
    assert ProposalStore(store.root).list() == []


def test_a_comment_with_an_email_and_no_known_identifiers_is_placeholdered(tmp_path):
    store = _store(tmp_path)
    clean, verify = _cleaners({})
    revised = route_feedback(
        [_comment("Ask ops@northwind.example for the schedule.", "Noted.")],
        store, at=AT, anonymize=clean, verify=verify)
    assert revised[0]["flywheel_routing"]["action_taken"].startswith("proposal:")
    [proposal] = ProposalStore(store.root).list()
    after = proposal["diff"]["comment"]["after"]
    assert "[CONTACT]" in after and "northwind.example" not in after


def test_a_clean_edit_routes_as_before(tmp_path):
    store = _store(tmp_path)
    clean, verify = _cleaners(BUYER)
    revised = route_feedback(
        [_edit("Northwind Regional Health runs 40 sites.",
               "Northwind Regional Health runs 14 sites.")],
        store, at=AT, anonymize=clean, verify=verify)
    assert revised[0]["flywheel_routing"]["action_taken"].startswith("proposal:")
    [proposal] = ProposalStore(store.root).list()
    assert "[CLIENT]" in proposal["diff"]["text"]["after"]


def test_a_waiver_whose_claim_names_a_party_is_blocked(tmp_path):
    store = _store(tmp_path)
    clean, verify = _cleaners(BUYER)
    event = {"event_id": "ev_w1", "pursuit_id": "pur_a", "kind": "waive_block",
             "at": "2026-09-04T12:00:00Z", "actor": "lead",
             "actor_role": "pursuit_lead", "section_id": "s1"}
    waivers = {("lead", "2026-09-04T12:00:00Z"): [
        {"section_id": "s1", "tier": 1, "waiver_reason": "verified by phone",
         "text": "Northwind's CFO (555) 214-8890 confirmed the count."}]}
    revised = route_feedback([event], store, at=AT, waivers=waivers,
                             anonymize=clean, verify=verify)
    action = revised[0]["flywheel_routing"]["action_taken"]
    assert action.startswith(BLOCKED_PREFIX) and "claim.after" in action
    assert ProposalStore(store.root).list() == []


def test_without_verify_the_door_behaves_as_before(tmp_path):
    """The parameter is optional: callers that pass no scanner (the
    P10 route_edits door) keep their contract."""
    store = _store(tmp_path)
    revised = route_feedback([_edit("NRH runs 40 sites.", "NRH runs 14 sites.")],
                             store, at=AT)
    assert revised[0]["flywheel_routing"]["action_taken"].startswith("proposal:")


# -- P29a (P3-23): the write-back door's RECORD of the same control ---------

def test_writeback_residue_is_listed_under_blocked_by_location(tmp_path):
    """The maintenance guide says BOTH flywheel responses list identifier
    residue under `blocked` by location; the write-back response used to
    fold it into `skipped` as prose, shape-identical to a benign skip."""
    import json

    from fastapi.testclient import TestClient

    from engine.web.server import create_app
    from tests.web.conftest import FIXED_AT, sign_in
    from tests.web.test_template_fill_web import HAND, _plant

    ws = tmp_path / "ws"
    KBStore(ws / "kb")
    app = create_app(ws, now=lambda: FIXED_AT)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        sign_in(client, "Fiona Filler")
        client.post("/api/pursuits", json={"pursuit_id": "pur_res"})
        pursuit = _plant(ws, "pur_res", all_prose=True)
        (pursuit.root / "brief.json").write_text(json.dumps(
            {"buyer": {"name": "Northwind Regional Health"}}), encoding="utf-8")
        values = dict(HAND)
        # a hand-typed case block: the acronym survives placeholdering
        values["s-h10"] = [{"client": "NRH and its subcontractor",
                            "scope": "Finance", "outcome": "Live"}]
        put = client.put("/api/pursuits/pur_res/writeback/hand-fill",
                         json={"values": values})
        assert put.status_code == 200, put.text
        confirmed = client.post("/api/pursuits/pur_res/writeback/confirm",
                                json={})
        assert confirmed.status_code == 200, confirmed.text
        flywheel = confirmed.json()["flywheel"]
    assert flywheel["proposals"] == []
    assert flywheel["blocked"] == [{"slot_id": "s-h10", "locations": ["body"]}]
    assert "s-h10" not in flywheel["skipped"]  # a block is not a benign skip
    assert not any("residue" in v for v in flywheel["skipped"].values())
