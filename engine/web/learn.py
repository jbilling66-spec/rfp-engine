"""The flywheel's call sites (P26b-2, P1-41; widened by P26c, P1-44 —
the owner's call: what the human said or built is carried forward).

Until P1-41 `write_card_signals` and `route_edits` were a library
nothing called. Accept is where a pursuit's feedback is final, so
accept is where the engine learns from it:

  1. route this pursuit's unprocessed EDITS, COMMENTS (with the agent's
     reply) and WAIVERS into proposals (the steward decides; nothing
     self-merges) — an edit's lesson onto every firm card its section
     cited, a comment to its reason's target or the playbook, a waiver
     to validation tuning with the claim and the reason from the
     annotated draft; append each routed event's revised line — same
     event_id, D30 last-wins;
  2. propose a fact card from every ANSWERED GAP no proposal carries yet
     (the owner's call at B116 §5: routed at accept, deduped on gap_id
     against the opt-in door);
  3. recompute edit_survival onto every cited card from the WHOLE
     corpus through the resolver's own production filter (B40/D18).

Every string a proposal carries is placeholdered first with the buyer's
names (the frozen brief's buyer and the org registry's aliases → the
CLIENT placeholder, `engine.kb.anonymize.apply_placeholders`) — pursuit
prose never lands on a firm card or in the drafter's prompt raw.

Both writes happen under the KB root's lock (P1-40), inside the pursuit
guard the accept door already holds (the ordering rule in
engine/contracts/locks.py). The accept event is durable before this
runs; a failure here is reported in the response, never an un-accept.
"""

import json
import re
from pathlib import Path

_WAIVED_SUFFIX = re.compile(r"by (?P<actor>.+) at (?P<at>\S+)$")


def _brief(pursuit) -> dict:
    from engine.contracts import ContractError
    try:
        return pursuit.read_frozen("bid_brief")
    except (FileNotFoundError, ContractError):
        pass
    try:
        return pursuit.read_artifact("brief.json")
    except FileNotFoundError:
        return {}


def buyer_identifiers(workspace: Path, pursuit) -> dict[str, str]:
    """The buyer's names → CLIENT: the brief's buyer.name and, when the
    pursuit is linked to an organization, every alias the registry
    knows (P17/C6). Empty when nothing is known — then nothing is
    replaced, and the harness (M-27) is the backstop."""
    from engine.contracts import ContractError
    from engine.workspace.orgs import read_org

    buyer = (_brief(pursuit).get("buyer") or {})
    names = [buyer.get("name") or ""]
    if buyer.get("org_id"):
        try:
            names.extend(read_org(workspace, buyer["org_id"]).get("known_as") or [])
        except ContractError:
            pass
    return {name.strip(): "CLIENT" for name in names if name and name.strip()}


def cited_by_section(records: list[dict], pursuit_id: str) -> dict[str, list[str]]:
    """{section_id: [kb_id]} from this pursuit's production cite lines —
    the same records card_survival attributes to, so a lesson lands on
    the cards the section actually drew on."""
    out: dict[str, set] = {}
    for record in records:
        if (record.get("record_type") != "kb_retrieval"
                or record.get("pursuit_id") != pursuit_id):
            continue
        kb = record.get("kb") or {}
        section = (record.get("target") or {}).get("section_id")
        if kb.get("step") != "cite" or not section:
            continue
        out.setdefault(section, set()).update(kb.get("cards_cited") or ())
    return {section: sorted(ids) for section, ids in out.items()}


def waived_claims(pursuit) -> dict[tuple, list[dict]]:
    """{(actor, at): [claim]} from the annotated draft — the waive_block
    event carries neither the claim nor the reason; the claim's first
    reason line ("waived over … by {actor} at {at}") and the event's
    (actor, at) are stamped from one `at` in the waiver route."""
    from engine.validation import annotate
    try:
        annotated = pursuit.read_artifact(annotate.VALIDATION_NAME)
    except FileNotFoundError:
        return {}
    out: dict[tuple, list[dict]] = {}
    for section in annotated.get("sections", []):
        for claim in section.get("claims", []):
            if claim.get("disposition") != "waived":
                continue
            reasons = claim.get("reasons") or []
            match = _WAIVED_SUFFIX.search(reasons[0]) if reasons else None
            if not match:
                continue
            out.setdefault((match["actor"], match["at"]), []).append({
                "claim_id": claim.get("claim_id"),
                "text": claim.get("text", ""),
                "waiver_reason": claim.get("waiver_reason", ""),
                "tier": claim.get("tier"),
                "section_id": section.get("section_id")})
    return out


def answered_gaps(pursuit) -> list[dict]:
    """Every answered gap with text, from the intake lane (the brief)
    and the plan lane (the live plan) — one vocabulary, gap_id."""
    gaps = []
    for gap in (_brief(pursuit).get("intake") or {}).get("gaps", []):
        if gap.get("status") == "answered" and gap.get("answer"):
            gaps.append(dict(gap))
    plan_path = pursuit.root / "plan.json"
    if plan_path.exists():
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        for section in plan.get("sections", []):
            for gap in section.get("gaps", []):
                if gap.get("status") == "answered" and gap.get("answer"):
                    gaps.append(dict(gap))
    return gaps


def _route_gaps(pursuit, kb_root: Path, *, at: str, by: str, clean) -> list[str]:
    from engine.flywheel.proposals import ProposalStore
    from engine.kb.curation import propose_gap_answer_card

    pursuit_id = pursuit.pursuit_id
    already = {p["source"].get("gap_id")
               for p in ProposalStore(kb_root).list()
               if p["source"].get("pursuit_id") == pursuit_id
               and p["source"].get("gap_id")}
    opened = []
    for gap in answered_gaps(pursuit):
        if gap.get("gap_id") in already:
            continue
        opened.append(propose_gap_answer_card(
            kb_root,
            gap={**gap, "answer": clean(gap["answer"]),
                 "question_to_human": clean(gap.get("question_to_human", ""))},
            pursuit_id=pursuit_id,
            operator=gap.get("answered_by") or by, at=at))
        already.add(gap.get("gap_id"))
    return opened


def learn_from_accept(workspace: Path, kb_root: Path, pursuit_id: str, *,
                      at: str, by: str = "") -> dict:
    """-> {"routed": [event_id], "proposals": [proposal_id],
           "gap_proposals": [proposal_id], "signals_written": [kb_id]}
       — or {"skipped": why}. `by` is the accepting operator: the human
       a gap proposal names when the answer itself recorded no one."""
    from engine.contracts import path_lock
    from engine.flywheel.routing import route_feedback
    from engine.flywheel.survival import write_card_signals
    from engine.kb.anonymize import apply_placeholders
    from engine.kb.store import KBStore
    from engine.metrics.resolver import Corpus
    from engine.validation.voice import prohibited_terms
    from engine.web.events import EventsLane
    from engine.workspace import PursuitDir

    workspace = Path(workspace)
    kb_root = Path(kb_root)
    if not kb_root.resolve().is_relative_to(workspace.resolve()):
        # Learned signals go onto the workspace's OWN firm KB. A server
        # serving a workspace with no kb/ falls back to the repository's
        # seed store; writing a pilot's survival scores into that would
        # dirty a committed golden. Reported, not silent.
        return {"skipped": f"the KB at {kb_root} is outside the workspace "
                           "— nothing learned onto a shared store"}
    pursuit = PursuitDir(workspace, pursuit_id)
    lane = EventsLane(pursuit)
    store = KBStore(kb_root)
    identifiers = buyer_identifiers(workspace, pursuit)

    def clean(text):
        return apply_placeholders(text, identifiers) if identifiers else text

    corpus = Corpus(workspace)
    records = corpus.runs()
    with path_lock(kb_root):
        revised = route_feedback(
            lane.read(), store, at=at, voice_terms=prohibited_terms(),
            cited=cited_by_section(records, pursuit_id),
            waivers=waived_claims(pursuit), anonymize=clean)
        for line in revised:
            lane.append_revised(line)
        gap_proposals = _route_gaps(pursuit, kb_root, at=at, by=by,
                                    clean=clean)
        written = write_card_signals(store, records, corpus.events())
    proposals = sorted({
        pid
        for line in revised
        if line["flywheel_routing"]["action_taken"].startswith("proposal:")
        for pid in line["flywheel_routing"]["action_taken"]
        .split(":", 1)[1].split(",")})
    return {"routed": [line["event_id"] for line in revised],
            "proposals": proposals, "gap_proposals": gap_proposals,
            "signals_written": written}


def learn_from_writeback(workspace: Path, kb_root: Path, pursuit_id: str, *,
                         at: str) -> dict:
    """The hand-fill trigger (P26c, P1-44; B116 §4e): at writeback
    confirm the values a human typed into the firm template are final.
    v1 rule — a CASE BLOCK (a table-shaped hand slot with no numeric
    field and no column locator) becomes a corpus case-study proposal
    in the human's own words; the metadata record, the inline line and
    any priced slot (the pricing grid — P3-1 untouched) stay with the
    pursuit, and every skip is named. Reopens when a pilot steward asks
    for a slot the rule skipped.

    -> {"proposals": [proposal_id], "skipped": {slot_id: why}} — or
    {"skipped": why} when the KB is not the workspace's own."""
    from engine.assembly.hand_fill import (HAND_FILL_NAME, case_block_slots,
                                           case_block_text, hand_slots,
                                           read_hand_fill)
    from engine.contracts import path_lock
    from engine.flywheel.proposals import ProposalStore
    from engine.kb.anonymize import apply_placeholders
    from engine.workspace import PursuitDir

    workspace = Path(workspace)
    kb_root = Path(kb_root)
    if not kb_root.resolve().is_relative_to(workspace.resolve()):
        return {"skipped": f"the KB at {kb_root} is outside the workspace "
                           "— nothing learned onto a shared store"}
    pursuit = PursuitDir(workspace, pursuit_id)
    record = read_hand_fill(pursuit)
    if record is None:
        return {"proposals": [],
                "skipped": {HAND_FILL_NAME: "no hand-completion record"}}
    frozen = pursuit.read_frozen("pursuit_plan")
    container = pursuit.read_artifact(frozen.get("slots_ref", "slots.json"))
    identifiers = buyer_identifiers(workspace, pursuit)

    def clean(text):
        return apply_placeholders(text, identifiers) if identifiers else text

    cases = {slot["slot_id"] for slot in case_block_slots(container)}
    proposals: list[str] = []
    skipped: dict[str, str] = {}
    for slot in hand_slots(container):
        slot_id = slot["slot_id"]
        value = record.get("values", {}).get(slot_id)
        if slot_id not in cases:
            skipped[slot_id] = ("not a case block — the metadata record, "
                                "the inline line and priced slots stay "
                                "with the pursuit (P3-1)")
            continue
        if not value:
            skipped[slot_id] = "no values entered"
            continue
        body = clean(case_block_text(slot, value))
        title = (slot.get("path") or slot.get("question_text")
                 or slot_id).strip()
        source = {"door": "flywheel", "pursuit_id": pursuit_id,
                  "slot_id": slot_id, "artifact": HAND_FILL_NAME}
        if record.get("entered_by"):
            source["operator"] = record["entered_by"]
        with path_lock(kb_root):
            proposal = ProposalStore(kb_root).open(
                source=source, target="corpus", kind="new_card", at=at,
                diff={"title": {"after": title[:80]},
                      "body": {"after": body},
                      "layer": {"after": "corpus"},
                      "doc_kind": {"after": "case_study"},
                      "grain": {"after": "chunk"},
                      "content_origin": {"after": "human_authored"}},
                note=(f"A case block completed by hand for this pursuit "
                      f"({slot_id}) — proposed as a corpus case study in "
                      f"the human's own words; a steward decides."))
        proposals.append(proposal["proposal_id"])
    return {"proposals": proposals, "skipped": skipped}
