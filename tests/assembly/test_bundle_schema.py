"""The submission-bundle contract holds its shape (P18/C1, B77§2 D2).

Schema-level floor only — the composer's writer-enforced per-status
obligations (produced carries sha256+facts_path, refused carries reason)
are proven where the composer lands (C3), the slot_count precedent.
"""

import pytest

from engine.contracts.validate import ContractError, validate


def _bundle(**overrides):
    body = {
        "pursuit_id": "pur_demo",
        "at": "2026-08-29T12:00:00Z",
        "composed_by": "pat.lee",
        "deliverables": [
            {
                "name": "demo-twin.xlsx",
                "path": "exports/writeback/demo-twin.xlsx",
                "lane": "xlsx_writeback",
                "source_file": "demo-twin.xlsx",
                "sha256": "a" * 64,
                "facts_path": "exports/writeback-facts.json",
                "revision_n": 0,
                "status": "produced",
            },
            {
                "name": "response.docx",
                "path": "exports/submission/response.docx",
                "lane": "submission_render",
                "status": "absent",
            },
        ],
    }
    body.update(overrides)
    return body


def test_bundle_with_produced_and_absent_entries_validates():
    validate("submission_bundle", _bundle())


def test_missing_deliverables_refuses():
    body = _bundle()
    del body["deliverables"]
    with pytest.raises(ContractError):
        validate("submission_bundle", body)


def test_unknown_property_refuses_at_both_grains():
    with pytest.raises(ContractError):
        validate("submission_bundle", _bundle(composed_at="nope"))
    body = _bundle()
    body["deliverables"][0]["byte_size"] = 12
    with pytest.raises(ContractError):
        validate("submission_bundle", body)


def test_status_and_lane_are_closed_vocabularies():
    body = _bundle()
    body["deliverables"][1]["status"] = "pending"
    with pytest.raises(ContractError):
        validate("submission_bundle", body)
    body = _bundle()
    body["deliverables"][0]["lane"] = "appendix"
    with pytest.raises(ContractError):
        validate("submission_bundle", body)
