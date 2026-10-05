"""P32b / P1-8 narrow (B145): the four free-form workspace records have
contracts. Each test builds the writer's own shape (read off the writer
at B145 §3a) and proves the kind accepts it and refuses a stranger —
a missing required field, a key the record never writes, a value
outside its vocabulary. Red before each schema's commit: the kind is
unknown to the contracts gate, so the good instance refuses too."""

import copy

import pytest

from engine.contracts import ContractError, validate

AT = "2026-10-05T09:00:00"
SHA = "0" * 64


def _refuses(kind, obj, *, match):
    with pytest.raises(ContractError, match=match):
        validate(kind, obj)


# --- pending_comments (events/pending.json) ---------------------------------

PENDING = {
    "next_cid": 4,
    "pending": [
        {"cid": "cmt_0001", "kind": "comment", "provenance": "internal",
         "section_id": "sec-1", "actor": "Pat Lead", "actor_role": "pursuit_lead",
         "at": AT, "revision": 0, "slot_id": "s-1", "text": "Tighten the opening."},
        {"cid": "cmt_0002", "kind": "edit", "provenance": "internal",
         "section_id": "sec-1", "actor": "Pat Lead", "actor_role": "pursuit_lead",
         "at": AT, "revision": 0, "before": "we will", "after": "the firm will",
         "edit_reason": "tone"},
        {"cid": "cmt_0003", "kind": "comment", "provenance": "external",
         "section_id": "sec-2", "actor": "share:sl_01:Guest", "actor_role": "external_reviewer",
         "at": AT, "revision": 0, "text": "Please quantify the savings.",
         "link_id": "sl_01", "display_name": "Guest",
         "screen_flags": [{"pattern_id": "ignore_previous", "excerpt": "ignore prev…"}],
         "included_by": "Jordan Reviewer", "included_at": AT},
    ],
}


def test_pending_comments_accepts_the_lanes_shape_and_refuses_a_stranger():
    validate("pending_comments", PENDING)
    validate("pending_comments", {"pending": [], "next_cid": 1})
    no_counter = {"pending": []}  # the pre-monotonic shape: refused (B145 §3c)
    _refuses("pending_comments", no_counter, match="pending_comments.*next_cid")
    stranger = copy.deepcopy(PENDING)
    stranger["pending"][0]["mood"] = "cheerful"
    _refuses("pending_comments", stranger, match="pending_comments.*mood")
    other_kind = copy.deepcopy(PENDING)
    other_kind["pending"][0]["kind"] = "accept"  # accepts append; they never pend
    _refuses("pending_comments", other_kind, match="pending_comments.*accept")
    bad_cid = copy.deepcopy(PENDING)
    bad_cid["pending"][0]["cid"] = "c1"
    _refuses("pending_comments", bad_cid, match="pending_comments.*cmt_")
    aliased = copy.deepcopy(PENDING)
    aliased["next_cid"] = 0
    _refuses("pending_comments", aliased, match="pending_comments.*next_cid")

# --- addendum_meta (addenda/<id>/meta.json) ---------------------------------

META = {
    "addendum_id": "addm_01", "filename": "addendum-1.pdf", "at": AT,
    "by": "Pat Lead", "scanned": True, "decision": None,
    "impacts": [{"section_id": "sec-1", "score": 2,
                 "matched_terms": ["schedule", "transition"]}],
}
META_REPLANNED = {
    **META, "decision": "replan", "decided_by": "Pat Lead", "decided_at": AT,
    "decision_note": "scope moved", "archived_frozen_sha256": SHA,
    "archived_draft_sha256": SHA, "archived_annotated_sha256": SHA,
}


def test_addendum_meta_accepts_both_decisions_and_refuses_a_stranger():
    validate("addendum_meta", META)
    validate("addendum_meta", {**META, "decision": "note_only",
                               "decided_by": "Pat Lead", "decided_at": AT,
                               "decision_note": ""})
    validate("addendum_meta", META_REPLANNED)
    validate("addendum_meta", {**META, "scanned": False, "impacts": [],
                               "note": "binary upload — no text scan"})
    _refuses("addendum_meta", {**META, "decision": "approved"},
             match="addendum_meta.*approved")
    _refuses("addendum_meta", {**META, "addendum_id": "1"},
             match="addendum_meta.*addm_")
    _refuses("addendum_meta", {**META_REPLANNED, "archived_frozen_sha256": "abc"},
             match="addendum_meta.*archived_frozen_sha256")
    _refuses("addendum_meta", {**META, "uploaded_from": "mail"},
             match="addendum_meta.*uploaded_from")
    missing = {k: v for k, v in META.items() if k != "scanned"}
    _refuses("addendum_meta", missing, match="addendum_meta.*scanned")

# --- revision_round (revisions/round_<n>.json) ------------------------------

ROUND = {
    "pursuit_id": "pur_x", "round_n": 1, "from_revision": 0, "to_revision": 1,
    "at": AT, "actor": "Robin Reviewer",
    "consumed_event_ids": {"internal": ["evt_0003"], "external": ["evt_0004"]},
    "dismissed_external_event_ids": ["evt_0005"],
    "external_screen_flags": [{"event_id": "evt_0004",
                               "pattern_id": "ignore_previous", "excerpt": "…"}],
    "sections": [{"section_id": "sec-1", "outcome": "revised", "warnings": []},
                 {"section_id": "sec-2", "outcome": "kept",
                  "warnings": ["edit cmt_0002: 'before' text not found verbatim"]}],
    "reval": {"sections_revalidated": ["sec-1"], "consistency_run": True,
              "redteam_dropped": True},
    "live_gap_digest": "0123456789ab",
}


def test_revision_round_accepts_the_commits_record_and_refuses_a_stranger():
    validate("revision_round", ROUND)
    bad_outcome = copy.deepcopy(ROUND)
    bad_outcome["sections"][0]["outcome"] = "accepted"
    _refuses("revision_round", bad_outcome, match="revision_round.*accepted")
    no_ids = copy.deepcopy(ROUND)
    del no_ids["consumed_event_ids"]["external"]
    _refuses("revision_round", no_ids, match="revision_round.*external")
    zero = {**ROUND, "round_n": 0}
    _refuses("revision_round", zero, match="revision_round.*round_n")
    _refuses("revision_round", {**ROUND, "live_gap_digest": "xyz"},
             match="revision_round.*live_gap_digest")
    _refuses("revision_round", {**ROUND, "model": "fake"},
             match="revision_round.*model")

# --- extraction_record (extraction.json) ------------------------------------

EXTRACTION = {
    "docs": [
        {"file": "rfp.pdf", "extractor": "docling", "extraction_fingerprint": "ext_abc123",
         "degraded": False, "flags": [], "mandatory_review": False},
        {"file": "pricing.xlsx", "extractor": "openpyxl", "extraction_fingerprint": "ext_def456",
         "degraded": True, "flags": ["partial_extraction", "legacy_extractor"],
         "mandatory_review": True},
    ],
    "two_path": {
        "rfp.pdf": {"tables_diffed": 2,
                    "findings": [{"table": 0, "row": 1, "col": 2, "kind": "value_differs",
                                  "a": "12", "b": "21"},
                                 {"table": 1, "row": 0, "col": 0, "kind": "only_in_a",
                                  "a": "Total"}]},
        "annex.pdf": {"tables_diffed": 0, "findings": [],
                      "error": "vlm path failed: timeout"},
    },
}


def test_extraction_record_accepts_the_intake_artifact_and_refuses_a_stranger():
    validate("extraction_record", EXTRACTION)
    validate("extraction_record", {"docs": [], "two_path": {}})
    unknown_flag = copy.deepcopy(EXTRACTION)
    unknown_flag["docs"][0]["flags"] = ["rotated_pages"]
    _refuses("extraction_record", unknown_flag, match="extraction_record.*rotated_pages")
    bare_finding = copy.deepcopy(EXTRACTION)
    bare_finding["two_path"]["rfp.pdf"]["findings"] = [{"table": 0}]
    _refuses("extraction_record", bare_finding, match="extraction_record.*row")
    _refuses("extraction_record", {"two_path": {}}, match="extraction_record.*docs")
    stranger = copy.deepcopy(EXTRACTION)
    stranger["docs"][0]["pages"] = 12
    _refuses("extraction_record", stranger, match="extraction_record.*pages")
