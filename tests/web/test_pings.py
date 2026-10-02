"""Pings + gaps (B37/D14/D15): the frozen clause "ping escalates on
injected 24h clock", the ping/answer writers of the dormant run-log gap
fields, mid-review gap opening, and the WP11 e2e: a gap left open at
Gate 2 rides to an awaiting slot, gets pinged, answered, and the next
revise round DRAFTS it — the engine asks instead of inventing."""

import json

import pytest
from fastapi.testclient import TestClient

from engine.cli.slice import DEMO_PACK, DEMO_RAMBLE, DEMO_WORKBOOK
from engine.llm import FakeCaller, TracedCaller
from engine.runlog import read_run
from engine.web.fake_script import revision_script
from engine.web.server import create_app
from tests.web.conftest import advance_past_gate0, FIXED_AT, sign_in, wait_job

T_23H59 = "2026-08-10T08:59:00"
T_24H01 = "2026-08-10T09:01:00"


@pytest.fixture(scope="module")
def gapped(tmp_path_factory):
    """The demo walk with ONE gap left open at Gate 2 — it rides into
    the draft as an awaiting slot, and validation still runs (pends are
    honest, not blockers)."""
    ws = tmp_path_factory.mktemp("web-pings") / "ws"

    def make_caller(log):
        return TracedCaller(FakeCaller(revision_script()), log)

    app = create_app(ws, make_caller=make_caller, now=lambda: FIXED_AT)
    client = TestClient(app, base_url="http://127.0.0.1")
    client.__enter__()
    sign_in(client, "Pat Pinger")
    client.post("/api/pursuits", json={"pursuit_id": "pur_ping"})
    for name, path in (("demo-twin.xlsx", DEMO_WORKBOOK),
                       ("ramble.md", DEMO_RAMBLE),
                       ("research-pack.md", DEMO_PACK)):
        client.put(f"/api/pursuits/pur_ping/inbox/{name}",
                   content=path.read_bytes())
    advance_past_gate0(client, "pur_ping")
    client.post("/api/pursuits/pur_ping/gate1",
                json={"decision": "approved"})
    job = client.post("/api/pursuits/pur_ping/jobs",
                      json={"kind": "advance"}).json()
    wait_job(client, job["id"])
    g2 = client.get("/api/pursuits/pur_ping/gate2").json()
    open_gaps = [(s["section_id"], g["gap_id"], g["slot_id"])
                 for s in g2["sections"] for g in s["gaps"]
                 if g["status"] == "open"]
    assert open_gaps, "the demo twin must carry an open gap"
    kept_open = open_gaps[0]
    dispose = [{"section_id": sid, "gap_id": gid,
                "action": "draft_flagged",
                "note": "Best effort; flag novel claims."}
               for sid, gid, _ in open_gaps[1:]]
    client.post("/api/pursuits/pur_ping/gate2", json={
        "decision": ("approved_with_edits" if dispose else "approved"),
        **({"edits": {"dispose": dispose}} if dispose else {}),
        })
    # drafting stops awaiting_gap (the open gap pends its slot)...
    job = client.post("/api/pursuits/pur_ping/jobs",
                      json={"kind": "advance"}).json()
    done = wait_job(client, job["id"], timeout=120)
    assert "awaiting_gap" in done["message"]
    # ...and the next advance validates the drafted sections regardless
    job = client.post("/api/pursuits/pur_ping/jobs",
                      json={"kind": "advance"}).json()
    done = wait_job(client, job["id"], timeout=120)
    assert done["state"] == "done", done["message"]
    yield client, ws, kept_open
    client.__exit__(None, None, None)


def test_ping_escalates_at_24h(gapped):
    client, ws, (sid, gap_id, slot_id) = gapped
    r = client.post(f"/api/pursuits/pur_ping/gaps/{gap_id}/ping",
                    json={"route_to": "sme"})
    assert r.status_code == 200
    ping = r.json()
    # T+23:59 — not escalated; T+24:01 — escalated with the routed alert
    client.app.state.clock = lambda: T_23H59  # P2-47: the SERVER clock moves
    fresh = client.get("/api/pings").json()
    row = next(x for x in fresh if x["ping_id"] == ping["ping_id"])
    assert row["escalated"] is False and "alert" not in row
    client.app.state.clock = lambda: T_24H01
    late = client.get("/api/pings").json()
    row = next(x for x in late if x["ping_id"] == ping["ping_id"])
    assert row["escalated"] is True
    assert row["alert"]["route_to"] == "pursuit_lead"
    assert row["pursuit_id"] == "pur_ping"
    # the gap run-log line carries pinged_at (the dormant field's writer)
    runs = sorted((ws / "pur_ping" / "runs").glob("*/run.jsonl"))
    gap_lines = [r for f in runs for r in read_run(f)
                 if r.get("record_type") == "gap"
                 and r["gap"].get("pinged_at")]
    assert any(g["gap"]["gap_id"] == gap_id for g in gap_lines)
    # a second ping of the same gap refuses (it is pinged, not open)
    again = client.post(f"/api/pursuits/pur_ping/gaps/{gap_id}/ping",
                        json={})
    assert again.status_code == 409


def test_answer_never_escalates_and_completes_next_round(gapped):
    client, ws, (sid, gap_id, slot_id) = gapped
    inbox = client.get(f"/api/pursuits/pur_ping/pings").json()
    ping = next(p for p in inbox if p["gap_id"] == gap_id)
    r = client.post(
        f"/api/pursuits/pur_ping/pings/{ping['ping_id']}/answer",
        json={"answer": "Use the parallel-run standard: four cycles."})
    assert r.status_code == 200
    # an answered ping never escalates, however late the clock
    client.app.state.clock = lambda: T_24H01
    late = client.get("/api/pings").json()
    row = next(x for x in late if x["ping_id"] == ping["ping_id"])
    assert "escalated" not in row and row["resolution"] == "answered"
    # double answer refuses
    assert client.post(
        f"/api/pursuits/pur_ping/pings/{ping['ping_id']}/answer",
        json={"answer": "again"}
    ).status_code == 409
    # D15: the next revise round DRAFTS the previously-awaiting slot
    envelope = json.loads(
        (ws / "pur_ping" / "drafts" / "draft.json").read_text())
    awaiting_before = [a["slot_id"] for e in envelope["sections"]
                       for a in e.get("answers", [])
                       if a.get("status") == "awaiting_disposition"]
    assert slot_id in awaiting_before
    job = client.post("/api/pursuits/pur_ping/revise",
                      json={})
    done = wait_job(client, job.json()["id"], timeout=120)
    assert done["state"] == "done", done["message"]
    envelope = json.loads(
        (ws / "pur_ping" / "drafts" / "draft.json").read_text())
    answer_row = next(a for e in envelope["sections"]
                      for a in e.get("answers", [])
                      if a["slot_id"] == slot_id)
    assert answer_row["status"] == "drafted"
    assert "gap answer" in answer_row["prose"] \
        or answer_row["prose"]  # drafted from the human's content
    assert envelope["revision_n"] == 1
    # and the answered gap's run-log line closed the loop
    runs = sorted((ws / "pur_ping" / "runs").glob("*/run.jsonl"))
    answered = [r for f in runs for r in read_run(f)
                if r.get("record_type") == "gap"
                and r["gap"].get("resolution") == "answered"]
    assert any(g["gap"]["gap_id"] == gap_id for g in answered)


def test_mid_review_gap_opening(gapped):
    client, ws, (sid, _, _) = gapped
    r = client.post("/api/pursuits/pur_ping/gaps", json={
        "section_id": sid,
        "question": "Do we hold the state-specific license this asks for?"})
    assert r.status_code == 200
    gap = r.json()
    assert gap["gap_id"].startswith("gap_pur_ping_review_")
    assert gap["status"] == "open"
    plan = json.loads((ws / "pur_ping" / "plan.json").read_text())
    live = [g["gap_id"] for s in plan["sections"]
            for g in s.get("gaps", [])]
    assert gap["gap_id"] in live
    # the frozen plan never moves (live-copy-vs-record)
    frozen = json.loads(
        (ws / "pur_ping" / "plan.frozen.json").read_text())
    assert gap["gap_id"] not in [g["gap_id"] for s in frozen["sections"]
                                 for g in s.get("gaps", [])]
    # guards: unknown section, empty question
    assert client.post("/api/pursuits/pur_ping/gaps", json={
        "section_id": "nope", "question": "x"}).status_code == 409
    assert client.post("/api/pursuits/pur_ping/gaps", json={
        "section_id": sid, "question": " "}).status_code == 409


def test_the_answered_journal_line_carries_the_text_and_survives_a_failed_plan_write(
        gapped, monkeypatch):
    """P3-17 (W2b 6, B136): P1-36's fix had no named test. The SME's text
    rides the append-only pings journal line BEFORE the live plan write;
    if that write fails, the answer is not lost and the ping is not
    answerable twice. Red under the recorded mutant (strip `answer` from
    the journal line in PingLane.answer)."""
    from engine.workspace import PursuitDir
    client, ws, (sid, _, _) = gapped
    gap = client.post("/api/pursuits/pur_ping/gaps", json={
        "section_id": sid,
        "question": "Which escrow agent does the firm name for this line?"}).json()
    ping = client.post(f"/api/pursuits/pur_ping/gaps/{gap['gap_id']}/ping",
                       json={"route_to": "sme"}).json()
    text = "The firm names Harbor Escrow Services for this line."
    real_write = PursuitDir.write_artifact

    def failing_plan_write(self, kind, doc, *args, **kwargs):
        if kind in ("pursuit_plan", "bid_brief"):
            raise OSError("disk full — the live plan write failed")
        return real_write(self, kind, doc, *args, **kwargs)

    monkeypatch.setattr(PursuitDir, "write_artifact", failing_plan_write)
    with pytest.raises(OSError):
        client.post(f"/api/pursuits/pur_ping/pings/{ping['ping_id']}/answer",
                    json={"answer": text})
    monkeypatch.undo()
    # the append-only record carries the SME's words — the plan write
    # that followed it failed, and the answer is still on disk
    lines = [json.loads(l) for l in
             (ws / "pur_ping" / "pings" / "pings.jsonl").read_text().splitlines()]
    mine = [l for l in lines if l.get("ping_id") == ping["ping_id"]
            and l.get("resolution") == "answered"]
    assert len(mine) == 1
    assert mine[0]["answer"] == text
    assert mine[0]["answered_by"]
    # and the ping reads as answered everywhere the journal is folded
    row = next(x for x in client.get("/api/pings").json()
               if x["ping_id"] == ping["ping_id"])
    assert row["resolution"] == "answered" and row["answer"] == text
    # a second answer refuses: the first one stood
    assert client.post(f"/api/pursuits/pur_ping/pings/{ping['ping_id']}/answer",
                       json={"answer": "again"}).status_code == 409
