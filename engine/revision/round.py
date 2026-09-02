"""The revise round (B37/D6/D7/D9/D10): pending batch against revision N
-> one revision_agent call per touched section -> targeted re-validation
-> transactional commit -> revision N+1.

Authorities: the FROZEN plan is structure (plan_sha256 keeps binding it,
byte-untouched); the LIVE plan carries gap dispositions — the
live-copy-vs-record pattern, and the round record digests the live gap
state it consumed. A round that changes nothing REFUSES: revision_n
never bumps over unchanged bytes. Human edits apply verbatim, human-
attributed — and are RE-AUDITED like model prose (humans introduce
claims too, D10).

Commit order (crash-convergent from the checkpoint): archive rev{N} pair
-> new draft.json (revision_n=N+1) -> rebuilt annotated draft (carried
sections keep verdicts with staleness re-derived at the new `at`;
waivers on changed prose do NOT carry; ranked_fixes and revised
sections' red_team scores DROPPED — absent-means-absent, a stale score
would lie) -> comment events finalized with agent_reply -> the round
record -> live-plan draft_status."""

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from engine.contracts import ContractError, validate, write_bytes_atomic
from engine.workspace.pursuit import _serialize
from engine.drafting import route
from engine.drafting.compose import VOICE_DEFAULT, load_voice_spec
from engine.kb import UseRestrictedCard, targeted_open
from engine.revision import compose, wire
from engine.validation import annotate, audit, claims, voice
from engine.validation.findings import emit_validation
from engine.validation.validate import (
    ANCHORS_DEFAULT,
    consistency_pass,
    validate_section,
)
from engine.web.events import EventsLane

ROOT = Path(__file__).resolve().parents[2]
STAGE = "review_loop"
AGENT = "revision_agent"


@dataclass
class RoundReport:
    status: str = "complete"  # complete | refused
    round_n: int = 0
    revised: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)
    pended: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _refuse(log, report, code, message) -> RoundReport:
    log.emit("error", stage=STAGE, error={
        "code": code, "message": message, "recoverable": True,
        "action_taken": "surfaced_to_human"})
    report.status = "refused"
    report.warnings.append(message)  # the caller surfaces the reason
    return report


def _prose_of(entry: dict) -> str:
    if entry.get("answers"):
        return " ".join(a.get("prose", "") for a in entry["answers"])
    return entry.get("prose", "")


def run_round(pursuit, caller, log, store, *, at: str, actor: str,
              voice_path=VOICE_DEFAULT, anchors_path=ANCHORS_DEFAULT,
              should_cancel=None) -> RoundReport:
    """should_cancel: optional callable polled BETWEEN sections (the
    cooperative-cancel contract, D2): finished sections keep their
    checkpointed work, the commit never runs, and the next round resumes
    from the checkpoint — drafting's kill asymmetry, inherited."""
    report = RoundReport()

    # --- refusal gates, all before any spend ----------------------------
    try:
        envelope = pursuit.read_artifact("drafts/draft.json")
        annotated = pursuit.read_artifact(annotate.VALIDATION_NAME)
        frozen_plan = pursuit.read_frozen("pursuit_plan")
        live_plan = pursuit.read_artifact("plan.json")
        frozen_brief = pursuit.read_frozen("bid_brief")
    except FileNotFoundError as exc:
        return _refuse(log, report, "missing_artifact",
                       f"the review loop starts after validation: {exc}")
    except ContractError as exc:
        return _refuse(log, report, "frozen_verification_failed", str(exc))
    draft_sha = pursuit.file_sha256("drafts/draft.json")
    # P26a Group B (P1-14): the round's checkpoint binds the envelope it
    # started from (draft_sha256_in) and, once the commit has written the
    # new envelope, the one it produced (draft_sha256_out). A crash AFTER
    # the draft write used to re-key the checkpoint out of existence and
    # trip stale_annotation forever; now that state resumes ITS round's
    # commit from the annotated rebuild on.
    resume_commit = False
    ckpt_key = None
    for stage in sorted(pursuit.completed_stages()):
        if not stage.startswith("review_round_"):
            continue
        payload = pursuit.checkpoint_payload(stage)
        if payload.get("draft_sha256_out") == draft_sha:
            ckpt_key, resume_commit = stage, True
            break
        if payload.get("draft_sha256_in") == draft_sha:
            ckpt_key = stage
    if not resume_commit and annotated.get("draft_sha256") != draft_sha:
        return _refuse(log, report, "stale_annotation",
                       "annotated draft does not match the envelope — "
                       "re-run validation first")

    lane = EventsLane(pursuit)
    pending = lane.pending()
    consumable = [p for p in pending
                  if p.get("provenance", "internal") == "internal"
                  or p.get("included_by")]
    # D15: a gap answered since the draft is round work in itself — the
    # awaiting slot becomes draftable NOW, comment or no comment. The
    # predicate is the JOIN: the envelope slot still awaits disposition
    # AND the live-plan gap is answered (a gap answered at Gate 2 was
    # already consumed by drafting and its slot is drafted).
    awaiting_slots: dict[str, set] = {}
    for entry in envelope.get("sections", []):
        waits = {a["slot_id"] for a in entry.get("answers", [])
                 if a.get("status") == "awaiting_disposition"}
        if waits:
            awaiting_slots[entry["section_id"]] = waits
    answered_gaps: dict[str, list[dict]] = {}
    for section in live_plan.get("sections", []):
        waits = awaiting_slots.get(section["section_id"], set())
        for gap in section.get("gaps", []):
            if gap.get("status") == "answered" \
                    and gap.get("slot_id") in waits:
                answered_gaps.setdefault(
                    section["section_id"], []).append(gap)
    if not consumable and not answered_gaps and not resume_commit:
        return _refuse(log, report, "empty_round",
                       "no pending comments, edits, or newly answered "
                       "gaps — a round that would change nothing refuses; "
                       "revision_n never bumps over unchanged bytes")

    round_n = (envelope["revision_n"] if resume_commit
               else envelope["revision_n"] + 1)
    report.round_n = round_n
    ckpt_key = ckpt_key or f"review_round_{round_n}"

    path = frozen_plan["path"]
    slots_by_id: dict = {}
    if path == "A_designated":
        container = pursuit.read_artifact(
            frozen_plan.get("slots_ref", "slots.json"))
        slots_by_id = {s["slot_id"]: s for s in container["slots"]}
    frozen_sections = {s["section_id"]: s
                       for s in frozen_plan.get("sections", [])}
    entries = {e["section_id"]: e for e in envelope["sections"]}
    annotated_sections = {s["section_id"]: s
                          for s in annotated.get("sections", [])}

    by_section: dict[str, list[dict]] = {}
    for item in consumable:
        by_section.setdefault(item["section_id"], []).append(item)
    for section_id in answered_gaps:
        by_section.setdefault(section_id, [])  # touched, comments or not
    unknown = sorted(set(by_section) - set(entries))
    if unknown:
        return _refuse(log, report, "unknown_section",
                       f"pending items target unknown section(s) {unknown}")

    log.emit("stage_start", stage=STAGE)
    voice_text = load_voice_spec(voice_path)
    ckpt = (pursuit.checkpoint_payload(ckpt_key)
            if ckpt_key in pursuit.completed_stages()
            else {"sections": {}, "complete": False,
                  "round_n": round_n, "draft_sha256_in": draft_sha})
    # a checkpointed section's REVISED ENTRY is restored into the
    # in-memory envelope on resume — the outcome alone re-committed the
    # old prose under a "revised" label (P1-14)
    for section_id, done in ckpt["sections"].items():
        if done.get("entry") is not None and section_id in entries:
            entries[section_id].clear()
            entries[section_id].update(done["entry"])

    # --- per touched section: revise ------------------------------------
    for section_id, items in sorted(by_section.items()):
        if section_id in ckpt["sections"]:
            continue
        if should_cancel and should_cancel():
            log.emit("stage_end", stage=STAGE)
            report.status = "cancelled"
            report.warnings.append(
                f"cancelled between sections — "
                f"{len(ckpt['sections'])} section(s) checkpointed, the "
                "commit never ran; the next round resumes")
            return report
        entry = entries[section_id]
        gap_answers = answered_gaps.get(section_id, [])
        if entry.get("status") != "drafted" and not gap_answers:
            report.warnings.append(
                f"{section_id}: not drafted ({entry.get('status')}) — its "
                "pending items stay for a later round")
            ckpt["sections"][section_id] = {"outcome": "kept",
                                            "replies": {}, "warnings": []}
            pursuit.checkpoint(ckpt_key, ckpt)
            continue

        comments = [i for i in items if i["kind"] == "comment"]
        edits = [i for i in items if i["kind"] == "edit"]
        internal = [c for c in comments
                    if c.get("provenance", "internal") == "internal"]
        external = [c for c in comments
                    if c.get("provenance") == "external"]
        warnings: list[str] = []

        # human edits apply first, verbatim, attributed (D9 fallback lane)
        edited = False
        for edit in edits:
            target_answers = entry.get("answers", [])
            hit = None
            for answer in target_answers:
                if edit.get("slot_id") and \
                        answer["slot_id"] != edit["slot_id"]:
                    continue
                if edit["before"] in (answer.get("prose") or ""):
                    hit = answer
                    break
            if hit is None:
                warnings.append(
                    f"edit {edit['cid']}: 'before' text not found verbatim "
                    "— refused (the anchoring contract); re-anchor and "
                    "resubmit")
                continue
            hit["prose"] = hit["prose"].replace(edit["before"],
                                                edit["after"], 1)
            edited = True

        # the agent revises when comments exist OR a gap answer opened
        # previously-awaiting slots (D15)
        section_result = {"outcome": "kept", "replies": {},
                          "warnings": warnings}
        if comments or gap_answers:
            frozen_section = frozen_sections.get(section_id, {})
            planned_ids = [h["kb_id"]
                           for h in frozen_section.get("kb_hits", [])]
            opened, card_frames = [], []
            canonical_bodies: dict[str, str] = {}
            target = {"section_id": section_id,
                      "section_type": entry["section_type"]}
            for kb_id in planned_ids:  # the RAG ban holds (B31(1))
                try:
                    body = targeted_open(store, kb_id, log=log, stage=STAGE,
                                         agent=AGENT,
                                         query=f"revise:{section_id}",
                                         target=target)
                except UseRestrictedCard:
                    warnings.append(f"{kb_id}: use_restriction honored at "
                                    "revise time — withheld")
                    continue
                front, _ = store.read_card(kb_id)
                opened.append(kb_id)
                card_frames.append(compose.wrap_kb_card(
                    kb_id, front.get("title", ""), body))
                if front.get("canonical_block"):
                    canonical_bodies[kb_id] = body

            rp = route.section_plan(frozen_section, slots_by_id, path)
            model_slots = [slots_by_id[l["slot_id"]] for l in rp["lanes"]
                           if l["lane"] == route.MODEL] \
                if path == "A_designated" else []
            answered_slot_ids = [g["slot_id"] for g in gap_answers]
            revisable = [a["slot_id"] for a in entry.get("answers", [])
                         if a.get("status") == "drafted"
                         or a["slot_id"] in answered_slot_ids]
            section_findings = annotated_sections.get(
                section_id, {}).get("findings", [])
            blocked = [c for c in annotated_sections.get(
                section_id, {}).get("claims", [])
                if c.get("disposition") == "block"]
            directive = compose.revision_directive(
                section_id, findings=section_findings,
                blocked_claims=blocked,
                canonical_bodies=canonical_bodies,
                slot_ids=revisable, path=path,
                gap_answers=gap_answers)
            prompt = compose.build_revision_prompt(
                voice_text=voice_text, frozen_brief=frozen_brief,
                model_slots=model_slots, card_frames=card_frames,
                entry=entry, internal_comments=internal,
                external_comments=external, directive=directive, path=path)
            system = (ROOT / "prompts" / AGENT / "prompt.md").read_text(
                encoding="utf-8")
            result = caller.call(AGENT, tier="mid", prompt=prompt,
                                 system=system, stage=STAGE,
                                 span_id=f"{section_id}:revise",
                                 parent_span=f"stage:{STAGE}", **target)
            cids = {c["cid"] for c in internal + external}
            try:
                replies, reply_warnings = wire.parse_replies(
                    result.text, allowed_event_ids=cids)
                warnings.extend(reply_warnings)
                if path == "A_designated":
                    changed, wire_warnings = wire.parse_revision_answers(
                        result.text, revisable=revisable,
                        opened_ids=set(opened))
                    warnings.extend(wire_warnings)
                    for answer in entry.get("answers", []):
                        new = changed.get(answer["slot_id"])
                        if new and new["prose"] != answer.get("prose"):
                            answer["prose"] = new["prose"]
                            answer["kb_ids"] = new["kb_ids"]
                            if answer.get("status") == \
                                    "awaiting_disposition":
                                # the answered gap's slot completes (D15)
                                answer["status"] = "drafted"
                                answer.pop("reason", None)
                            edited = True
                    if entry.get("status") == "awaiting_disposition" \
                            and all(a.get("status") != "awaiting_disposition"
                                    for a in entry.get("answers", [])):
                        entry["status"] = "drafted"
                else:
                    new, wire_warnings = wire.parse_revision_prose(
                        result.text, opened_ids=set(opened))
                    warnings.extend(wire_warnings)
                    if entry.get("answers"):
                        answer = entry["answers"][0]
                        if new["prose"] != answer.get("prose"):
                            answer["prose"] = new["prose"]
                            answer["kb_ids"] = new["kb_ids"]
                            edited = True
                    elif new["prose"] != entry.get("prose"):
                        entry["prose"] = new["prose"]
                        entry["kb_ids"] = new["kb_ids"]
                        edited = True
                section_result["replies"] = replies
            except wire.WireError as exc:
                # prior prose kept — a failed round never half-applies
                warnings.append(f"{section_id}: {exc} — section pended, "
                                "prose unchanged")
                section_result["outcome"] = "pended"

        if section_result["outcome"] != "pended":
            section_result["outcome"] = "revised" if edited else "kept"
        section_result["warnings"] = warnings
        if section_result["outcome"] == "revised":
            section_result["entry"] = json.loads(json.dumps(entry))
        ckpt["sections"][section_id] = section_result
        pursuit.checkpoint(ckpt_key, ckpt)

    outcomes = {sid: r["outcome"] for sid, r in ckpt["sections"].items()}
    revised = sorted(s for s, o in outcomes.items() if o == "revised")
    report.revised = revised
    report.kept = sorted(s for s, o in outcomes.items() if o == "kept")
    report.pended = sorted(s for s, o in outcomes.items() if o == "pended")
    for r in ckpt["sections"].values():
        report.warnings.extend(r.get("warnings", []))

    if not revised:
        pursuit.clear_checkpoint(ckpt_key)
        log.emit("stage_end", stage=STAGE)
        return _refuse(log, report, "nothing_changed",
                       "no section changed — revision_n never bumps over "
                       "unchanged bytes (comments answered nothing, edits "
                       "failed to anchor, or wires pended)")

    # --- targeted re-validation (D10) -----------------------------------
    if not ckpt.get("reval_done"):
        facts = claims.fact_catalog(store)
        facts_by_id = {c["kb_id"]: c for c in facts}
        catalog_ids = frozenset(facts_by_id)
        terms = voice.prohibited_terms(voice_path)
        flag_demand: dict = {}
        for section in frozen_plan["sections"]:
            matched, section_level = set(), False
            for gap in section.get("gaps", []):
                if gap.get("status") != "draft_flagged":
                    continue
                slot = gap.get("slot_id")
                if slot is None or slot not in section.get("slot_ids", []):
                    section_level = True
                else:
                    matched.add(slot)
            flag_demand[section["section_id"]] = (frozenset(matched),
                                                 section_level)
        ckpt["reval"] = {}
        for section_id in revised:
            ckpt["reval"][section_id] = validate_section(
                pursuit, caller, log, store, entries[section_id],
                slots_by_id, facts_by_id, catalog_ids,
                flag_demand.get(section_id, (frozenset(), False)),
                terms, at, report)
        drafted_entries = [e for e in envelope["sections"]
                           if e["status"] == "drafted"]
        consistency = consistency_pass(caller, log, drafted_entries,
                                       slots_by_id, report)
        # as_dict encodes section identity only inside finding_id — keep
        # the section key alongside for the rebuild grouping
        ckpt["consistency"] = [
            {"section_id": f.section_id, "finding": f.as_dict()}
            for f in consistency]
        ckpt["reval_done"] = True
        pursuit.checkpoint(ckpt_key, ckpt)

    # --- convergent commit (P1-14) ----------------------------------------
    # Every step below is safe to replay: the archives and the envelope
    # write happen once (skipped when this run resumes a commit whose
    # envelope already landed), the annotated rebuild is idempotent, the
    # finalize dedupes on cid, the round record is kept from the first
    # attempt, the plan write is idempotent, and the checkpoint is
    # cleared LAST — a crash anywhere converges on the next run with
    # zero model calls.
    rev_dir = pursuit.root / "revisions"
    rev_dir.mkdir(exist_ok=True)
    prior_n = round_n - 1
    draft_path = pursuit.root / "drafts" / "draft.json"
    if not resume_commit:
        for name, src in ((f"draft.rev{prior_n}.json", draft_path),
                          (f"annotated.rev{prior_n}.json",
                           pursuit.root / annotate.VALIDATION_NAME)):
            if not (rev_dir / name).exists():  # archived once, never rewritten
                write_bytes_atomic(rev_dir / name, src.read_bytes())
        envelope["revision_n"] = round_n
        validate("draft", envelope)
        new_bytes = _serialize(envelope).encode("utf-8")
        new_sha = hashlib.sha256(new_bytes).hexdigest()
        # the binding is recorded BEFORE the write, so a crash between the
        # two leaves a checkpoint the next run resolves either way
        ckpt["draft_sha256_out"] = new_sha
        pursuit.checkpoint(ckpt_key, ckpt)
        draft_path = pursuit.write_artifact("draft", envelope,
                                            name="drafts/draft.json")
        assert hashlib.sha256(draft_path.read_bytes()).hexdigest() == new_sha
    else:
        new_sha = draft_sha
        report.warnings.append(
            f"round {round_n}: resumed its commit after a crash — the "
            "envelope had already landed; finishing from the annotated "
            "rebuild")
    log.emit("artifact", stage=STAGE, artifact={
        "kind": "draft", "path": str(draft_path), "revision_n": round_n,
        "sha256": new_sha})

    consistency_by_section: dict[str, list[dict]] = {}
    for row in ckpt.get("consistency", []):
        consistency_by_section.setdefault(
            row["section_id"], []).append(row["finding"])
    per_section: dict[str, dict] = {}
    scores: dict[str, dict] = {}
    catalog = claims.fact_catalog(store)  # once, not per carried claim
    for entry in envelope["sections"]:
        section_id = entry["section_id"]
        if entry.get("status") != "drafted":
            continue
        old = annotated_sections.get(section_id, {})
        if section_id in ckpt.get("reval", {}):
            fresh = ckpt["reval"][section_id]
            per_section[section_id] = {
                "claims": fresh["claims"],
                "findings": (fresh["findings"]
                             + consistency_by_section.get(section_id, [])),
                "warnings": fresh.get("warnings", []),
            }
            # red_team scores for revised prose are DROPPED (D10) — a
            # score over text that no longer exists would lie
        else:
            carried_claims = [dict(c) for c in old.get("claims", [])]
            for claim in carried_claims:
                # deterministic staleness re-derivation at the NEW at: a
                # fact card lapsing between rounds must not leave its
                # claim marked supported
                ref = claim.get("fact_sheet_ref")
                if ref and claim.get("status") == "supported":
                    row = next((c for c in catalog if c["kb_id"] == ref),
                               None)
                    if row is not None and audit.is_stale(row, at=at):
                        claim["status"] = "stale"
                        claim["disposition"] = "flag"
                        claim.setdefault("reasons", []).insert(
                            0, f"fact card {ref} lapsed by {at} — "
                               "re-verify before shipping")
            old_findings = [f for f in old.get("findings", [])
                            if f.get("check") != "consistency"]
            per_section[section_id] = {
                "claims": carried_claims,
                "findings": (old_findings
                             + consistency_by_section.get(section_id, [])),
                "warnings": [],
            }
            if "red_team" in old:
                scores[section_id] = old["red_team"]

    rebuilt = annotate.build_annotated(
        envelope=envelope, per_section=per_section, scores=scores,
        ranked_fixes=[],  # dropped every round: fixes describe old prose
        validated_at=at, draft_sha256=new_sha)
    annotated_path = pursuit.write_artifact(
        "annotated_draft", rebuilt, name=annotate.VALIDATION_NAME)
    log.emit("artifact", stage=STAGE, artifact={
        "kind": "annotated_draft", "path": str(annotated_path),
        "revision_n": round_n,
        "sha256": annotate.artifact_digest(annotated_path)})

    # finalize consumed comment events; drop consumed pending
    all_replies = {cid: reply for r in ckpt["sections"].values()
                   for cid, reply in r.get("replies", {}).items()}

    already = lane.finalized_by_cid()  # P1-14: replay never re-appends

    def _finalize(item, *, with_reply: bool):
        if item["cid"] in already:
            return already[item["cid"]]
        fields = {"cid": item["cid"],
                  "section_id": item["section_id"],
                  "section_type": entries[item["section_id"]]
                  .get("section_type")}
        if item["kind"] == "comment":
            fields["comment_text"] = item["text"]
            if with_reply and item["cid"] in all_replies:
                fields["agent_reply"] = all_replies[item["cid"]]
        else:
            fields.update({"before": item["before"],
                           "after": item["after"]})
            if item.get("edit_reason"):
                fields["edit_reason"] = item["edit_reason"]
        return lane.append(item["kind"], at=at, actor=item["actor"],
                           actor_role=item["actor_role"], **fields)

    consumed_ids: list[tuple] = []
    for item in consumable:
        if item["section_id"] in report.pended:
            continue  # a pended section's items stay for the next round
        # D16c: an INCLUDED external comment that the screen flagged
        # leaves its durable trace line in the round's run
        if item.get("provenance") == "external" \
                and item.get("screen_flags"):
            emit_validation(
                log, check="injection_screen", result="flag",
                target={"section_id": item["section_id"],
                        "section_type": entries[item["section_id"]]
                        .get("section_type")})
        consumed_ids.append((item, _finalize(item, with_reply=True)))
    # D16d: dismissed external comments finalize WITHOUT a reply — the
    # record never silently drops external input
    dismissed_ids: list[tuple] = []
    consumed_cids = {i["cid"] for i, _ in consumed_ids}
    for item in pending:
        if (item.get("provenance") == "external"
                and item.get("dismissed_by")
                and item["cid"] not in consumed_cids
                and item["section_id"] in entries
                and item["section_id"] not in report.pended):
            dismissed_ids.append((item, _finalize(item, with_reply=False)))
    lane.drop_pending(consumed_cids | {i["cid"] for i, _ in dismissed_ids})
    if resume_commit and not consumed_ids:
        # the pending items were consumed and dropped before the crash;
        # the finalized events (each carrying its cid) are the record of
        # what this round consumed
        consumed_ids = [(e, e) for e in already.values()
                        if e.get("revision") == prior_n
                        and e.get("kind") in ("comment", "edit")]

    # the round record (D6): code-validated, the artifact kind `revision`
    record = {
        "pursuit_id": pursuit.pursuit_id,
        "round_n": round_n,
        "from_revision": prior_n,
        "to_revision": round_n,
        "at": at,
        "actor": actor,
        "consumed_event_ids": {
            "internal": [e["event_id"] for i, e in consumed_ids
                         if i.get("provenance", "internal") == "internal"],
            "external": [e["event_id"] for i, e in consumed_ids
                         if i.get("provenance") == "external"],
        },
        "dismissed_external_event_ids": [
            e["event_id"] for _, e in dismissed_ids],
        "external_screen_flags": [
            {"event_id": e["event_id"], "pattern_id": f["pattern_id"],
             "excerpt": f["excerpt"]}
            for i, e in consumed_ids
            if i.get("provenance") == "external"
            for f in i.get("screen_flags", [])],
        "sections": [{"section_id": sid, "outcome": r["outcome"],
                      "warnings": r.get("warnings", [])}
                     for sid, r in sorted(ckpt["sections"].items())],
        "reval": {"sections_revalidated": revised,
                  "consistency_run": True, "redteam_dropped": True},
        "live_gap_digest": hashlib.sha256(json.dumps(
            [[s["section_id"],
              [(g.get("gap_id"), g.get("status"))
               for g in s.get("gaps", [])]]
             for s in live_plan.get("sections", [])],
            sort_keys=True).encode("utf-8")).hexdigest()[:12],
    }
    record_name = f"revisions/round_{round_n}.json"
    if (pursuit.root / record_name).exists():
        # the first attempt's record stands (its `at` is the commit's
        # own clock); a replay completes the round around it
        record_path = pursuit.root / record_name
        report.warnings.append(
            f"round {round_n}: record kept from the first attempt")
    else:
        record_path = pursuit.write_json(record_name, record)
    log.emit("artifact", stage=STAGE, artifact={
        "kind": "revision", "path": str(record_path),
        "revision_n": round_n,
        "sha256": hashlib.sha256(
            record_path.read_bytes()).hexdigest()})

    # live-plan draft_status: revised sections are validated again (D11)
    for section in live_plan.get("sections", []):
        if section["section_id"] in revised \
                and section.get("draft_status") == "in_review":
            section["draft_status"] = "validated"
    pursuit.write_artifact("pursuit_plan", live_plan)
    pursuit.clear_checkpoint(ckpt_key)  # the round is committed (P1-14)

    log.emit("stage_end", stage=STAGE)
    return report
