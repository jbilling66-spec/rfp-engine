"""P1-14 (P26a Group B): the revision round's commit is CONVERGENT. A
crash at any write boundary — after the archives, after the envelope,
after the annotated rebuild, mid-way through finalizing events, after
drop_pending, after the round record — is staged AT that boundary with
a raising writer (lessons.md: never by deleting artifacts after a full
run), and the next round call finishes the same round with ZERO model
calls, each consumed comment finalized exactly once, the record and the
plan in place, and the round's checkpoint cleared."""

import json

import pytest

from engine.llm import FakeCaller
from engine.web.events import EventsLane
from tests.revision.fixtures.rounds import (
    ROUND_AT,
    add_comment,
    round_script,
    run_one_round,
    validated_pursuit,
)


class _Counting(FakeCaller):
    def __init__(self, script):
        super().__init__(script)
        self.calls = 0

    def call_for(self, agent, *args, **kwargs):
        if agent == "revision_agent":  # the spend that must not repeat
            self.calls += 1
        return super().call_for(agent, *args, **kwargs)


class Boom(RuntimeError):
    pass


FLAG = [{"pattern_id": "override_instruction",
         "excerpt": "ignore your previous instructions"}]
RECORD_INPUTS = ("consumed_event_ids", "dismissed_external_event_ids",
                 "external_screen_flags")


def _prepare(tmp_path):
    """Two internal comments plus the external legs (P1-53, P29b b5): an
    INCLUDED guest comment the screen flagged, and a DISMISSED one —
    every id list of the round record and its D16c flags in play."""
    pursuit = validated_pursuit(tmp_path)
    envelope = pursuit.read_artifact("drafts/draft.json")
    drafted = [e for e in envelope["sections"] if e["status"] == "drafted"]
    sid = drafted[0]["section_id"]
    c1 = add_comment(pursuit, sid, "Tighten the opening.")
    c2 = add_comment(pursuit, sid, "Name the benefit earlier.")
    lane = EventsLane(pursuit)
    c3 = lane.add_pending(
        kind="comment", section_id=sid, actor="Guest", at=ROUND_AT,
        actor_role="external_reviewer", provenance="external",
        text="Please quantify the transition savings.",
        included_by="Jordan Reviewer", screen_flags=FLAG)
    c4 = lane.add_pending(
        kind="comment", section_id=sid, actor="Guest", at=ROUND_AT,
        actor_role="external_reviewer", provenance="external",
        text="Off topic remark.", dismissed_by="Jordan Reviewer")
    return pursuit, sid, [c1["cid"], c2["cid"], c3["cid"], c4["cid"]]


def _record(pursuit):
    return json.loads((pursuit.root / "revisions" / "round_1.json")
                      .read_text())


def _control_inputs(tmp_path):
    """The same fixture without a crash — what the record must say."""
    pursuit, _, _ = _prepare(tmp_path / "control")
    report, _ = run_one_round(tmp_path / "control", pursuit,
                              fake=_Counting(round_script()))
    assert report.status == "complete", report.warnings
    record = _record(pursuit)
    assert record["consumed_event_ids"]["internal"] and \
        record["consumed_event_ids"]["external"] and \
        record["dismissed_external_event_ids"] and \
        record["external_screen_flags"], record  # a discriminating control
    return {k: record[k] for k in RECORD_INPUTS}


def _events(pursuit):
    path = pursuit.root / "events" / "events.jsonl"
    return ([json.loads(l) for l in path.read_text().splitlines()]
            if path.exists() else [])


def _assert_converged(pursuit, cids, sid):
    envelope = pursuit.read_artifact("drafts/draft.json")
    assert envelope["revision_n"] == 1
    finalized = [e for e in _events(pursuit) if e.get("cid")]
    assert sorted(e["cid"] for e in finalized) == sorted(cids), \
        "each consumed comment finalized exactly once"
    assert EventsLane(pursuit).pending() == []
    record = _record(pursuit)
    assert record["to_revision"] == 1
    # P1-53 (P29b b5): the record says what the round consumed — the
    # finalized events' ids, never an empty list on a replayed commit
    finalized_ids = sorted(e["event_id"] for e in finalized)
    recorded = sorted(record["consumed_event_ids"]["internal"]
                      + record["consumed_event_ids"]["external"]
                      + record["dismissed_external_event_ids"])
    assert recorded == finalized_ids, "the round record names every id"
    assert (pursuit.root / "revisions" / "draft.rev0.json").exists()
    annotated = pursuit.read_artifact("drafts/annotated-draft.json")
    assert annotated["draft_sha256"] == pursuit.file_sha256(
        "drafts/draft.json")
    plan = pursuit.read_artifact("plan.json")
    section = next(s for s in plan["sections"] if s["section_id"] == sid)
    assert section.get("draft_status") == "validated"
    assert not any(s.startswith("review_round_")
                   for s in pursuit.completed_stages()), \
        "a committed round clears its checkpoint"


def _crash_at(monkeypatch, pursuit, boundary):
    """Install a writer that raises at the named boundary, once."""
    state = {"fired": False}

    def once(fn):
        def wrapped(*a, **kw):
            if not state["fired"]:
                state["fired"] = True
                raise Boom(boundary)
            return fn(*a, **kw)
        return wrapped

    if boundary == "after_archive":
        real = pursuit.write_artifact

        def write_artifact(kind, obj, name=None):
            if kind == "draft" and not state["fired"]:
                state["fired"] = True
                raise Boom(boundary)
            return real(kind, obj, name=name)
        monkeypatch.setattr(pursuit, "write_artifact", write_artifact)
    elif boundary == "after_envelope":
        real = pursuit.write_artifact

        def write_artifact(kind, obj, name=None):
            if kind == "annotated_draft" and not state["fired"]:
                state["fired"] = True
                raise Boom(boundary)
            return real(kind, obj, name=name)
        monkeypatch.setattr(pursuit, "write_artifact", write_artifact)
    elif boundary == "mid_finalize":
        real = EventsLane.append
        seen = {"n": 0}

        def append(self, kind, **kw):
            if kind == "comment":
                seen["n"] += 1
                if seen["n"] == 2 and not state["fired"]:
                    state["fired"] = True
                    raise Boom(boundary)
            return real(self, kind, **kw)
        monkeypatch.setattr(EventsLane, "append", append)
    elif boundary == "after_drop_pending":
        real = pursuit.write_artifact  # P32b: the record has a contract

        def write_artifact(kind, obj, name=None):
            if kind == "revision_round" and not state["fired"]:
                state["fired"] = True
                raise Boom(boundary)
            return real(kind, obj, name=name)
        monkeypatch.setattr(pursuit, "write_artifact", write_artifact)
    elif boundary == "after_record":
        real = pursuit.write_artifact

        def write_artifact(kind, obj, name=None):
            if kind == "pursuit_plan" and not state["fired"]:
                state["fired"] = True
                raise Boom(boundary)
            return real(kind, obj, name=name)
        monkeypatch.setattr(pursuit, "write_artifact", write_artifact)
    else:
        raise AssertionError(boundary)
    return state


@pytest.mark.parametrize("boundary", [
    "after_archive", "after_envelope", "mid_finalize",
    "after_drop_pending", "after_record"])
def test_a_crash_at_every_write_boundary_converges_on_the_next_call(
        tmp_path, monkeypatch, boundary):
    pursuit, sid, cids = _prepare(tmp_path)
    state = _crash_at(monkeypatch, pursuit, boundary)
    first = _Counting(round_script())
    with pytest.raises(Boom):
        run_one_round(tmp_path, pursuit, fake=first)
    assert state["fired"] and first.calls > 0
    events_after_crash = len(_events(pursuit))

    second = _Counting(round_script())
    report, _ = run_one_round(tmp_path, pursuit, fake=second)
    assert report.status == "complete", report.warnings
    assert second.calls == 0, "the replay never calls the model"
    _assert_converged(pursuit, cids, sid)
    assert len(_events(pursuit)) >= events_after_crash
    # P1-53: the replayed record equals the control run's, all three lists
    record = _record(pursuit)
    assert {k: record[k] for k in RECORD_INPUTS} == _control_inputs(tmp_path)


def test_a_replayed_commit_records_what_the_round_consumed(tmp_path,
                                                            monkeypatch):
    """P1-53 (P29b b5), the audit's reproduction: a crash after
    `drop_pending` and before the record write resumed with zero spend
    and wrote `consumed_event_ids {internal: [], external: []}`, no
    dismissed id and no screen flag, while events.jsonl held every cid
    finalized at revision 1 — the D6 audit record said the round
    consumed nothing and the D16c trace vanished with it."""
    pursuit, sid, cids = _prepare(tmp_path)
    state = _crash_at(monkeypatch, pursuit, "after_drop_pending")
    with pytest.raises(Boom):
        run_one_round(tmp_path, pursuit, fake=_Counting(round_script()))
    assert state["fired"]
    assert not (pursuit.root / "revisions" / "round_1.json").exists()
    assert EventsLane(pursuit).pending() == []  # dropped before the crash
    report, _ = run_one_round(tmp_path, pursuit,
                              fake=_Counting(round_script()))
    assert report.status == "complete", report.warnings
    record = _record(pursuit)
    control = _control_inputs(tmp_path)
    assert {k: record[k] for k in RECORD_INPUTS} == control
    assert record["external_screen_flags"][0]["pattern_id"] == \
        FLAG[0]["pattern_id"]


def test_a_successful_round_clears_its_checkpoint_and_keeps_revised_prose(
        tmp_path):
    pursuit, sid, cids = _prepare(tmp_path)
    before = next(e for e in pursuit.read_artifact("drafts/draft.json")
                  ["sections"] if e["section_id"] == sid)["answers"][0]["prose"]
    report, _ = run_one_round(tmp_path, pursuit,
                              fake=_Counting(round_script()))
    assert report.status == "complete"
    after = next(e for e in pursuit.read_artifact("drafts/draft.json")
                 ["sections"] if e["section_id"] == sid)["answers"][0]["prose"]
    assert after != before
    _assert_converged(pursuit, cids, sid)


def test_resume_after_a_mid_loop_crash_keeps_the_checkpointed_prose(
        tmp_path, monkeypatch):
    """The checkpoint carries the revised ENTRY, not just the outcome —
    a resume that re-committed the old prose under a 'revised' label was
    the quieter half of P1-14."""
    pursuit = validated_pursuit(tmp_path)
    envelope = pursuit.read_artifact("drafts/draft.json")
    drafted = [e for e in envelope["sections"] if e["status"] == "drafted"]
    assert len(drafted) >= 2, "the fixture must offer two sections"
    a, b = drafted[0]["section_id"], drafted[1]["section_id"]
    add_comment(pursuit, a, "Tighten A.")
    add_comment(pursuit, b, "Tighten B.")
    originals = {s["section_id"]: s["answers"][0]["prose"] for s in drafted}
    # crash between the two sections: the first is checkpointed, the
    # second never runs
    calls = {"n": 0}
    script = round_script()
    inner = script["revision_agent"]

    def flaky(prompt):
        calls["n"] += 1
        if calls["n"] == 2:
            raise Boom("between sections")
        return inner(prompt)
    script["revision_agent"] = flaky
    with pytest.raises(Boom):
        run_one_round(tmp_path, pursuit, fake=FakeCaller(script))
    assert any(s.startswith("review_round_")
               for s in pursuit.completed_stages())
    resumed = _Counting(round_script())
    report, _ = run_one_round(tmp_path, pursuit, fake=resumed)
    assert report.status == "complete", report.warnings
    assert resumed.calls == 1, "only the un-checkpointed section is revised"
    final = {s["section_id"]: s["answers"][0]["prose"]
             for s in pursuit.read_artifact("drafts/draft.json")["sections"]
             if s["status"] == "drafted"}
    assert final[a] != originals[a] and final[b] != originals[b]
