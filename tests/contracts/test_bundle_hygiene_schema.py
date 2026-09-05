"""P3-15 (P26b-3) — the submission-bundle schema's `hygiene` block: what
a produced deliverable carries at the part level, on the record. Closed
shape; firm_identity is a two-value enum; counts and part names only."""

import pytest

from engine.contracts import ContractError, validate

AT = "2026-09-04T12:00:00Z"


def _bundle(entry_extra: dict) -> dict:
    return {"pursuit_id": "pur_x", "at": AT, "composed_by": "Pat Lead",
            "deliverables": [{
                "name": "response.docx",
                "path": "exports/submission/response.docx",
                "lane": "submission_render", "status": "produced",
                "sha256": "0" * 64, **entry_extra}]}


HYGIENE = {"creator": "Fixture Advisory LLP",
           "last_modified_by": "Fixture Advisory LLP", "parts": 14,
           "comment_parts": [], "media_parts": [], "revision_marks": {},
           "generator_strings": [], "firm_identity": "configured"}


def test_a_produced_entry_takes_a_hygiene_block():
    validate("submission_bundle", _bundle({"hygiene": HYGIENE}))
    validate("submission_bundle", _bundle({"hygiene": {
        **HYGIENE, "comment_parts": ["word/comments.xml"],
        "revision_marks": {"w:ins": 2}, "firm_identity": "unconfigured"}}))


def test_the_block_is_closed_and_the_identity_is_an_enum():
    with pytest.raises(ContractError):
        validate("submission_bundle", _bundle({"hygiene": {
            **HYGIENE, "text": "never text"}}))
    with pytest.raises(ContractError):
        validate("submission_bundle", _bundle({"hygiene": {
            **HYGIENE, "firm_identity": "the firm"}}))
    with pytest.raises(ContractError):
        validate("submission_bundle", _bundle({"hygiene": {
            k: v for k, v in HYGIENE.items() if k != "parts"}}))
